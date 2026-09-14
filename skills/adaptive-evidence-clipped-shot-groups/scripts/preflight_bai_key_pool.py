#!/usr/bin/env python3
"""Check a 中转站 key pool before uploads or semantic analysis without exposing keys."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

import requests


def read_keys(path: Path) -> list[str]:
    result = []
    for raw in path.read_text(encoding="utf-8-sig").replace(",", "\n").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if "=" in value:
            value = value.split("=", 1)[1].strip().strip('"').strip("'")
        if value and value not in result:
            result.append(value)
    if not result:
        raise RuntimeError("中转站 key pool is empty")
    return result


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def pool_fingerprint(keys: list[str]) -> str:
    material = "\n".join(sorted(fingerprint(key) for key in keys))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def probe(slot: int, key: str, endpoint: str, model: str, max_output_tokens: int, timeout: int) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Return exactly OK."}],
        "stream": False,
        "max_tokens": max_output_tokens,
        "temperature": 0,
    }
    base = {"slot": slot, "fingerprint": fingerprint(key)}
    try:
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json; charset=utf-8"},
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=(30, timeout),
        )
        match = re.search(r"balance=(\d+)\s+required=(\d+)", response.text, re.I)
        if match:
            return {**base, "status": "insufficient", "http_status": response.status_code,
                    "balance_credits": int(match.group(1)), "required_credits": int(match.group(2))}
        if response.ok:
            usage = (response.json().get("usage") or {}) if response.content else {}
            return {**base, "status": "usable", "http_status": response.status_code,
                    "probe_total_tokens": usage.get("total_tokens")}
        status = "request_rejected"
        try:
            status = str((response.json().get("error") or {}).get("code") or status)
        except Exception:
            pass
        return {**base, "status": status, "http_status": response.status_code}
    except Exception as exc:
        return {**base, "status": "network_error", "detail": type(exc).__name__}


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=path.stem + "_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-pool-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default="gemini-3.6-flash")
    parser.add_argument("--endpoint", default="https://api.b.ai/v1/chat/completions")
    parser.add_argument("--max-output-tokens", type=int, default=30000)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--cache-seconds", type=float, default=300)
    args = parser.parse_args()

    keys = read_keys(args.key_pool_file.resolve())
    if args.workers < 1 or args.cache_seconds < 0:
        raise RuntimeError("workers must be positive and cache-seconds must be non-negative")
    current_pool_fingerprint = pool_fingerprint(keys)
    if args.cache_seconds and args.output.is_file():
        try:
            cached = json.loads(args.output.read_text(encoding="utf-8-sig"))
            age = time.time() - float(cached.get("checked_at_epoch") or 0)
            if (
                0 <= age <= args.cache_seconds
                and cached.get("pool_fingerprint") == current_pool_fingerprint
                and cached.get("model") == args.model
                and cached.get("endpoint") == args.endpoint
                and cached.get("usable_slots")
            ):
                print(json.dumps({
                    "key_count": len(keys),
                    "usable_slots": cached["usable_slots"],
                    "output": args.output.name,
                    "cache_status": "reused",
                    "cache_age_seconds": round(age, 3),
                }, ensure_ascii=False))
                return 0
        except Exception:
            pass
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(args.workers, len(keys))) as pool:
        futures = [
            pool.submit(probe, slot, key, args.endpoint, args.model, args.max_output_tokens, args.timeout)
            for slot, key in enumerate(keys, start=1)
        ]
        results = [future.result() for future in futures]
    usable = [item["slot"] for item in results if item["status"] == "usable"]
    payload = {
        "schema_version": "0.1-bai-key-preflight",
        "model": args.model,
        "endpoint": args.endpoint,
        "pool_fingerprint": current_pool_fingerprint,
        "checked_at_epoch": time.time(),
        "key_count": len(keys),
        "usable_slots": usable,
        "results": results,
    }
    atomic_json(args.output.resolve(), payload)
    print(json.dumps({"key_count": len(keys), "usable_slots": usable, "output": args.output.name, "cache_status": "fresh"}, ensure_ascii=False))
    return 0 if usable else 2


if __name__ == "__main__":
    raise SystemExit(main())
