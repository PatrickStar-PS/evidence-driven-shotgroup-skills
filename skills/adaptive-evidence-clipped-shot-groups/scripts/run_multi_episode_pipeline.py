#!/usr/bin/env python3
"""Execute resumable per-episode command DAGs with two-level concurrency."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path


WORKSPACE_SCHEMA = "1.0-adaptive-range-workspace"
WORKSPACE_SUBDIRS = (
    "inputs",
    "evidence",
    "request",
    "response",
    "normalized",
    "audit",
    "retry",
    "logs",
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


def command_fingerprint(command: dict) -> str:
    payload = {
        "argv": command.get("argv"),
        "cwd": command.get("cwd"),
        "environment": command.get("environment"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def safe_component(value: str, label: str) -> str:
    if not value or value in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise RuntimeError(f"{label} must contain only letters, digits, dot, underscore, or hyphen")
    return value


def prepare_workspace(work_dir: Path, episode: str, stage: str, command_id: str) -> tuple[Path, str]:
    workspace = (
        work_dir
        / safe_component(episode, "episode")
        / safe_component(stage, "stage")
        / safe_component(command_id, "command id")
    ).resolve()
    root = work_dir.resolve()
    if root != workspace and root not in workspace.parents:
        raise RuntimeError(f"range workspace escaped work root: {workspace}")
    workspace.mkdir(parents=True, exist_ok=True)
    for name in WORKSPACE_SUBDIRS:
        (workspace / name).mkdir(exist_ok=True)
    contract = {
        "schema_version": WORKSPACE_SCHEMA,
        "episode": episode,
        "stage": stage,
        "range_id": command_id,
        "workspace": str(workspace),
        "subdirectories": list(WORKSPACE_SUBDIRS),
    }
    contract_sha256 = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    contract["contract_sha256"] = contract_sha256
    atomic_json(workspace / "workspace.json", contract)
    return workspace, contract_sha256


class StatusWriter:
    def __init__(self, path: Path, initial: dict):
        self.path = path.resolve()
        self.lock = threading.Lock()
        self.data = initial
        if self.path.is_file():
            try:
                existing = json.loads(self.path.read_text(encoding="utf-8-sig"))
                if existing.get("manifest_sha256") == initial.get("manifest_sha256"):
                    self.data = existing
            except Exception:
                pass

    def update_command(
        self,
        episode: str,
        stage: str,
        command_id: str,
        payload: dict,
    ) -> None:
        with self.lock:
            episode_data = self.data.setdefault("episodes", {}).setdefault(episode, {})
            stage_data = episode_data.setdefault("stages", {}).setdefault(stage, {})
            stage_data.setdefault("commands", {})[command_id] = payload
            episode_data["updated_at_epoch"] = time.time()
            self.data["updated_at_epoch"] = time.time()
            atomic_json(self.path, self.data)

    def update_stage(self, episode: str, stage: str, status: str) -> None:
        with self.lock:
            episode_data = self.data.setdefault("episodes", {}).setdefault(episode, {})
            stage_data = episode_data.setdefault("stages", {}).setdefault(stage, {})
            stage_data["status"] = status
            stage_data["updated_at_epoch"] = time.time()
            episode_data["updated_at_epoch"] = time.time()
            self.data["updated_at_epoch"] = time.time()
            atomic_json(self.path, self.data)

    def update_episode(self, episode: str, status: str) -> None:
        with self.lock:
            episode_data = self.data.setdefault("episodes", {}).setdefault(episode, {})
            episode_data["status"] = status
            episode_data["updated_at_epoch"] = time.time()
            self.data["updated_at_epoch"] = time.time()
            atomic_json(self.path, self.data)

    def reusable(
        self,
        episode: str,
        stage: str,
        command: dict,
        workspace_sha256: str,
    ) -> bool:
        with self.lock:
            record = (
                self.data.get("episodes", {})
                .get(episode, {})
                .get("stages", {})
                .get(stage, {})
                .get("commands", {})
                .get(str(command["id"]), {})
            )
            return (
                record.get("status") == "complete"
                and record.get("command_sha256") == command_fingerprint(command)
                and record.get("workspace_contract_sha256") == workspace_sha256
            )


def run_command(
    episode: str,
    stage: str,
    command: dict,
    writer: StatusWriter,
    logs_dir: Path,
    work_dir: Path,
    resume: bool,
    local_gate: threading.BoundedSemaphore | None = None,
) -> dict:
    command_id = str(command.get("id") or "")
    argv = command.get("argv")
    if not command_id or not isinstance(argv, list) or not argv:
        raise RuntimeError(f"{episode}/{stage}: command requires id and argv list")
    workspace, workspace_sha256 = prepare_workspace(
        work_dir, episode, stage, command_id
    )
    if resume and writer.reusable(
        episode, stage, command, workspace_sha256
    ):
        return {"id": command_id, "status": "reused"}
    command_sha256 = command_fingerprint(command)
    log_path = workspace / "logs" / f"{command_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    writer.update_command(
        episode,
        stage,
        command_id,
        {
            "status": "running",
            "command_sha256": command_sha256,
            "workspace": str(workspace),
            "workspace_contract_sha256": workspace_sha256,
            "started_at_epoch": started,
            "log_path": str(log_path.resolve()),
        },
    )
    environment = os.environ.copy()
    for key, value in (command.get("environment") or {}).items():
        environment[str(key)] = str(value)
    environment.update({
        "ADAPTIVE_RANGE_WORKDIR": str(workspace),
        "ADAPTIVE_EPISODE_ID": episode,
        "ADAPTIVE_STAGE_ID": stage,
        "ADAPTIVE_RANGE_ID": command_id,
    })
    with log_path.open("w", encoding="utf-8") as log:
        if local_gate is not None:
            local_gate.acquire()
        try:
            completed = subprocess.run(
                [str(part) for part in argv],
                cwd=command.get("cwd") or workspace,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        finally:
            if local_gate is not None:
                local_gate.release()
    finished = time.time()
    record = {
        "status": "complete" if completed.returncode == 0 else "failed",
        "command_sha256": command_sha256,
        "workspace": str(workspace),
        "workspace_contract_sha256": workspace_sha256,
        "returncode": completed.returncode,
        "started_at_epoch": started,
        "finished_at_epoch": finished,
        "elapsed_seconds": round(finished - started, 3),
        "log_path": str(log_path.resolve()),
    }
    writer.update_command(episode, stage, command_id, record)
    if completed.returncode != 0:
        raise RuntimeError(
            f"{episode}/{stage}/{command_id} failed with code "
            f"{completed.returncode}; see {log_path}"
        )
    return {"id": command_id, "status": "complete"}


def run_episode(
    episode_data: dict,
    writer: StatusWriter,
    logs_dir: Path,
    work_dir: Path,
    range_workers: int,
    local_workers: int,
    resume: bool,
    local_gate: threading.BoundedSemaphore,
) -> dict:
    episode = str(episode_data.get("episode") or "")
    if not episode:
        raise RuntimeError("episode entry requires episode")
    writer.update_episode(episode, "running")
    try:
        for stage in episode_data.get("stages") or []:
            stage_name = str(stage.get("name") or "")
            if not stage_name:
                raise RuntimeError(f"episode {episode}: stage requires name")
            commands = list(stage.get("commands") or [])
            stage_kind = str(stage.get("kind") or "relay")
            default_workers = local_workers if stage_kind == "local" else range_workers
            workers = int(stage.get("workers") or default_workers)
            workers = min(max(1, workers), max(1, len(commands)))
            writer.update_stage(episode, stage_name, "running")
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(
                        run_command,
                        episode,
                        stage_name,
                        command,
                        writer,
                        logs_dir,
                        work_dir,
                        resume,
                        local_gate if stage_kind == "local" else None,
                    )
                    for command in commands
                ]
                for future in concurrent.futures.as_completed(futures):
                    future.result()
            writer.update_stage(episode, stage_name, "complete")
        writer.update_episode(episode, "complete")
        return {"episode": episode, "status": "complete"}
    except Exception as exc:
        writer.update_episode(episode, "failed")
        return {"episode": episode, "status": "failed", "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run multiple episode pipelines concurrently while each episode runs its own range commands concurrently."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--logs-dir", type=Path, required=True)
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="Stable per-range workspace root (default: <status-parent>/workspaces)",
    )
    parser.add_argument("--episode-workers", type=int, default=3)
    parser.add_argument("--range-workers", type=int, default=8)
    parser.add_argument("--local-workers", type=int, default=2)
    parser.add_argument(
        "--resume", action=argparse.BooleanOptionalAction, default=True
    )
    args = parser.parse_args()
    if min(args.episode_workers, args.range_workers, args.local_workers) < 1:
        raise RuntimeError("worker counts must be positive")
    manifest_path = args.manifest.resolve()
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
    if manifest.get("schema_version") != "1.0-adaptive-batch-command-manifest":
        raise RuntimeError("unsupported batch manifest schema_version")
    episodes = list(manifest.get("episodes") or [])
    episode_ids = [str(item.get("episode") or "") for item in episodes]
    if not episodes or len(set(episode_ids)) != len(episode_ids):
        raise RuntimeError("batch manifest episodes are empty or duplicated")

    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    initial = {
        "schema_version": "1.0-adaptive-batch-status",
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "execution": {
            "episode_workers": args.episode_workers,
            "range_workers": args.range_workers,
            "local_workers": args.local_workers,
            "resume_enabled": args.resume,
        },
        "episodes": {},
        "created_at_epoch": time.time(),
        "updated_at_epoch": time.time(),
    }
    writer = StatusWriter(args.status, initial)
    args.logs_dir.mkdir(parents=True, exist_ok=True)
    work_dir = (args.work_dir or (args.status.resolve().parent / "workspaces")).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    writer.data.setdefault("execution", {})["work_dir"] = str(work_dir)
    atomic_json(writer.path, writer.data)
    results: list[dict] = []
    local_gate = threading.BoundedSemaphore(args.local_workers)
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(args.episode_workers, len(episodes))
    ) as pool:
        futures = [
            pool.submit(
                run_episode,
                episode,
                writer,
                args.logs_dir.resolve(),
                work_dir,
                args.range_workers,
                args.local_workers,
                args.resume,
                local_gate,
            )
            for episode in episodes
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item["episode"])
    failed = [item for item in results if item["status"] != "complete"]
    print(
        json.dumps(
            {
                "episodes": len(results),
                "complete": len(results) - len(failed),
                "failed": failed,
                "status": str(args.status.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
