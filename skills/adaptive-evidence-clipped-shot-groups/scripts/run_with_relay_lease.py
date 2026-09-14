#!/usr/bin/env python3
"""Run one relay command under a renewable cross-window key-slot lease."""

from __future__ import annotations

import argparse
import subprocess
import threading
import time
from pathlib import Path

from relay_slot_leases import (
    DEFAULT_DB,
    RelayLeaseStore,
    acquire_with_wait,
    usable_keys,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--per-key-concurrency", type=int, default=2)
    parser.add_argument("--global-limit", type=int, default=30)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--phase", default="primary")
    parser.add_argument("--lease-seconds", type=float, default=900)
    parser.add_argument("--wait-seconds", type=float, default=600)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--command-attempts", type=int, default=2)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise RuntimeError("a command is required after --")
    if not any("{key_offset}" in part or "{key_slot}" in part for part in command):
        raise RuntimeError(
            "command must contain {key_offset} or {key_slot} so the lease is enforced"
        )
    if args.command_attempts < 1:
        raise RuntimeError("command-attempts must be positive")

    keys = usable_keys(args.preflight.resolve())
    excluded: set[str] = set()
    last_returncode = 1
    for command_attempt in range(1, args.command_attempts + 1):
        store = RelayLeaseStore(args.database)
        lease = acquire_with_wait(
            store,
            keys,
            args.per_key_concurrency,
            args.global_limit,
            args.owner,
            args.phase,
            args.lease_seconds,
            args.wait_seconds,
            args.poll_seconds,
            excluded,
        )
        stop = threading.Event()

        def renew() -> None:
            interval = max(1.0, min(30.0, args.lease_seconds / 3.0))
            while not stop.wait(interval):
                try:
                    store.heartbeat(lease["lease_id"], args.lease_seconds)
                except Exception:
                    # The child remains authoritative; lease expiry is the safe fallback.
                    pass

        heartbeat = threading.Thread(target=renew, daemon=True)
        heartbeat.start()
        try:
            concrete = [
                part.replace("{key_offset}", str(lease["key_offset"])).replace(
                    "{key_slot}", str(lease["key_slot"])
                )
                for part in command
            ]
            completed = subprocess.run(concrete)
            last_returncode = completed.returncode
        finally:
            stop.set()
            heartbeat.join(timeout=2)
            try:
                store.release(lease["lease_id"])
            finally:
                store.close()
        if last_returncode == 0:
            return 0
        excluded.add(lease["key_fingerprint"])
        if len(excluded) >= len(keys):
            break
        if command_attempt < args.command_attempts:
            time.sleep(min(5.0, float(command_attempt)))
    return last_returncode


if __name__ == "__main__":
    raise SystemExit(main())
