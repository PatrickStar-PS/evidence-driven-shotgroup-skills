#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


KEY_NAMES = {
    "BAI_KEY_POOL",
    "BAI_API_KEY_POOL",
    "BAI_API_KEYS",
    "BAI_API_KEY",
}


def parse_env(path: Path) -> list[str]:
    values: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() not in KEY_NAMES:
            continue
        value = value.strip().strip('"').strip("'")
        values.extend(part for part in re.split(r"[\s,;|]+", value) if part)
    return values


def parse_key_file(path: Path) -> list[str]:
    values: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").replace(",", "\n").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if "=" in value:
            value = value.split("=", 1)[1].strip().strip('"').strip("'")
        if value:
            values.append(value)
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a relay key pool without printing secrets.")
    parser.add_argument("--env-file", type=Path, action="append", default=[])
    parser.add_argument("--key-file", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    keys: list[str] = []
    for env_file in args.env_file:
        if env_file.exists():
            keys.extend(parse_env(env_file))
    for key_file in args.key_file:
        if key_file.exists():
            keys.extend(parse_key_file(key_file))
    for name in KEY_NAMES:
        value = os.environ.get(name, "").strip().strip('"').strip("'")
        if value:
            keys.extend(part for part in re.split(r"[\s,;|]+", value) if part)
    unique = list(dict.fromkeys(keys))
    if not unique:
        raise RuntimeError("No relay keys found in the supplied environment files")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(unique) + "\n", encoding="utf-8")
    print(f"relay key pool ready: {len(unique)} key(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
