#!/usr/bin/env python3
"""Cross-process relay slot leases without exposing API keys."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path


DEFAULT_DB = (
    Path.home()
    / ".codex"
    / "state"
    / "adaptive-evidence-clipped-shot-groups"
    / "relay-slots.sqlite3"
)


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=path.stem + "_", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def usable_keys(preflight_path: Path) -> list[dict]:
    data = json.loads(preflight_path.read_text(encoding="utf-8-sig"))
    result = [
        {
            "key_slot": int(item["slot"]),
            "fingerprint": str(item["fingerprint"]),
        }
        for item in data.get("results") or []
        if item.get("status") == "usable"
    ]
    result.sort(key=lambda item: item["key_slot"])
    if not result:
        raise RuntimeError("preflight has no usable relay key")
    if len({item["fingerprint"] for item in result}) != len(result):
        raise RuntimeError("preflight contains duplicate key fingerprints")
    return result


class RelayLeaseStore:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            self.path, timeout=30, isolation_level=None, check_same_thread=False
        )
        self.connection.execute("PRAGMA busy_timeout=30000")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS relay_leases (
                lease_id TEXT PRIMARY KEY,
                key_fingerprint TEXT NOT NULL,
                key_slot INTEGER NOT NULL,
                lane INTEGER NOT NULL,
                owner TEXT NOT NULL,
                phase TEXT NOT NULL,
                created_at REAL NOT NULL,
                heartbeat_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                UNIQUE(key_fingerprint, lane)
            )
            """
        )

    def close(self) -> None:
        self.connection.close()

    def _clean_expired(self, now: float) -> None:
        self.connection.execute(
            "DELETE FROM relay_leases WHERE expires_at <= ?", (now,)
        )

    def try_acquire(
        self,
        keys: list[dict],
        per_key_concurrency: int,
        global_limit: int,
        owner: str,
        phase: str,
        lease_seconds: float,
        excluded_fingerprints: set[str] | None = None,
    ) -> dict | None:
        if per_key_concurrency < 1 or global_limit < 1 or lease_seconds <= 0:
            raise ValueError("concurrency limits and lease duration must be positive")
        excluded_fingerprints = excluded_fingerprints or set()
        now = time.time()
        fingerprints = [item["fingerprint"] for item in keys]
        placeholders = ",".join("?" for _ in fingerprints)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._clean_expired(now)
            active_total = self.connection.execute(
                f"SELECT COUNT(*) FROM relay_leases WHERE key_fingerprint IN ({placeholders})",
                fingerprints,
            ).fetchone()[0]
            if active_total >= global_limit:
                self.connection.execute("COMMIT")
                return None
            rows = self.connection.execute(
                f"SELECT key_fingerprint, lane FROM relay_leases WHERE key_fingerprint IN ({placeholders})",
                fingerprints,
            ).fetchall()
            occupied: dict[str, set[int]] = {}
            for fingerprint, lane in rows:
                occupied.setdefault(str(fingerprint), set()).add(int(lane))
            candidates = sorted(
                (
                    len(occupied.get(item["fingerprint"], set())),
                    item["key_slot"],
                    item,
                )
                for item in keys
                if item["fingerprint"] not in excluded_fingerprints
                and len(occupied.get(item["fingerprint"], set()))
                < per_key_concurrency
            )
            if not candidates:
                self.connection.execute("COMMIT")
                return None
            item = candidates[0][2]
            used = occupied.get(item["fingerprint"], set())
            lane = next(
                lane
                for lane in range(1, per_key_concurrency + 1)
                if lane not in used
            )
            lease_id = uuid.uuid4().hex
            expires_at = now + lease_seconds
            self.connection.execute(
                """
                INSERT INTO relay_leases
                (lease_id, key_fingerprint, key_slot, lane, owner, phase,
                 created_at, heartbeat_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lease_id,
                    item["fingerprint"],
                    item["key_slot"],
                    lane,
                    owner,
                    phase,
                    now,
                    now,
                    expires_at,
                ),
            )
            self.connection.execute("COMMIT")
            return {
                "lease_id": lease_id,
                "key_slot": item["key_slot"],
                "key_offset": item["key_slot"] - 1,
                "key_fingerprint": item["fingerprint"],
                "lane": lane,
                "owner": owner,
                "phase": phase,
                "expires_at": expires_at,
                "database": str(self.path),
            }
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def heartbeat(self, lease_id: str, lease_seconds: float) -> bool:
        now = time.time()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._clean_expired(now)
            cursor = self.connection.execute(
                """
                UPDATE relay_leases
                SET heartbeat_at = ?, expires_at = ?
                WHERE lease_id = ?
                """,
                (now, now + lease_seconds, lease_id),
            )
            self.connection.execute("COMMIT")
            return cursor.rowcount == 1
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def release(self, lease_id: str) -> bool:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.connection.execute(
                "DELETE FROM relay_leases WHERE lease_id = ?", (lease_id,)
            )
            self.connection.execute("COMMIT")
            return cursor.rowcount == 1
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def status(self) -> list[dict]:
        now = time.time()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._clean_expired(now)
            rows = self.connection.execute(
                """
                SELECT lease_id, key_fingerprint, key_slot, lane, owner, phase,
                       created_at, heartbeat_at, expires_at
                FROM relay_leases
                ORDER BY key_slot, lane
                """
            ).fetchall()
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return [
            {
                "lease_id": row[0],
                "key_fingerprint": row[1],
                "key_slot": row[2],
                "lane": row[3],
                "owner": row[4],
                "phase": row[5],
                "created_at": row[6],
                "heartbeat_at": row[7],
                "expires_at": row[8],
            }
            for row in rows
        ]


def acquire_with_wait(
    store: RelayLeaseStore,
    keys: list[dict],
    per_key_concurrency: int,
    global_limit: int,
    owner: str,
    phase: str,
    lease_seconds: float,
    wait_seconds: float,
    poll_seconds: float,
    excluded_fingerprints: set[str] | None = None,
) -> dict:
    deadline = time.monotonic() + wait_seconds
    while True:
        lease = store.try_acquire(
            keys,
            per_key_concurrency,
            global_limit,
            owner,
            phase,
            lease_seconds,
            excluded_fingerprints,
        )
        if lease is not None:
            return lease
        if time.monotonic() >= deadline:
            raise TimeoutError("timed out waiting for a reusable relay key slot")
        time.sleep(max(0.05, poll_seconds))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Coordinate reusable relay key slots across Codex windows."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    subparsers = parser.add_subparsers(dest="command", required=True)

    acquire_parser = subparsers.add_parser("acquire")
    acquire_parser.add_argument("--preflight", type=Path, required=True)
    acquire_parser.add_argument("--per-key-concurrency", type=int, default=2)
    acquire_parser.add_argument("--global-limit", type=int, default=30)
    acquire_parser.add_argument("--owner", required=True)
    acquire_parser.add_argument("--phase", default="primary")
    acquire_parser.add_argument("--lease-seconds", type=float, default=900)
    acquire_parser.add_argument("--wait-seconds", type=float, default=600)
    acquire_parser.add_argument("--poll-seconds", type=float, default=0.5)
    acquire_parser.add_argument("--output", type=Path)

    heartbeat_parser = subparsers.add_parser("heartbeat")
    heartbeat_parser.add_argument("--lease-id", required=True)
    heartbeat_parser.add_argument("--lease-seconds", type=float, default=900)

    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("--lease-id", required=True)

    subparsers.add_parser("status")
    args = parser.parse_args()
    store = RelayLeaseStore(args.database)
    try:
        if args.command == "acquire":
            lease = acquire_with_wait(
                store,
                usable_keys(args.preflight.resolve()),
                args.per_key_concurrency,
                args.global_limit,
                args.owner,
                args.phase,
                args.lease_seconds,
                args.wait_seconds,
                args.poll_seconds,
            )
            if args.output:
                atomic_json(args.output.resolve(), lease)
            print(json.dumps(lease, ensure_ascii=False))
        elif args.command == "heartbeat":
            print(
                json.dumps(
                    {
                        "lease_id": args.lease_id,
                        "renewed": store.heartbeat(
                            args.lease_id, args.lease_seconds
                        ),
                    },
                    ensure_ascii=False,
                )
            )
        elif args.command == "release":
            print(
                json.dumps(
                    {
                        "lease_id": args.lease_id,
                        "released": store.release(args.lease_id),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            leases = store.status()
            print(
                json.dumps(
                    {"active": len(leases), "leases": leases},
                    ensure_ascii=False,
                )
            )
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
