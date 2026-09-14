#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path

from relay_slot_leases import RelayLeaseStore


def main() -> int:
    keys = [
        {"key_slot": 1, "fingerprint": "key-a"},
        {"key_slot": 2, "fingerprint": "key-b"},
        {"key_slot": 3, "fingerprint": "key-c"},
    ]
    with tempfile.TemporaryDirectory(prefix="relay-slot-test-") as temporary:
        store = RelayLeaseStore(Path(temporary) / "slots.sqlite3")
        try:
            leases = [
                store.try_acquire(keys, 2, 5, f"owner-{index}", "primary", 60)
                for index in range(5)
            ]
            assert all(leases)
            counts = Counter(item["key_fingerprint"] for item in leases if item)
            assert sorted(counts.values()) == [1, 2, 2], counts
            assert store.try_acquire(keys, 2, 5, "overflow", "primary", 60) is None
            assert store.release(leases[0]["lease_id"])
            replacement = store.try_acquire(keys, 2, 5, "replacement", "seam", 60)
            assert replacement is not None
            assert store.heartbeat(replacement["lease_id"], 120)
            assert len(store.status()) == 5
            store.connection.execute("UPDATE relay_leases SET expires_at = 0")
            assert store.status() == []
        finally:
            store.close()
    print("relay slot leases: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
