"""
Leakage-safe dataset splitting (F-04).

* Split **source assets before synthesis**: items that share any group key value
  (speaker, recording, session, room, noise, …) are bound into one group and
  land in one split (:func:`assign_groups`).
* :func:`check_split_leakage` checks *every* split pair (train–val included, not
  only test vs train/val) for shared key values.
* :class:`SessionRegistry` refuses to register one real session for two uses
  (e.g. dev and blind_test).
* :func:`verify_benchmark_manifest` compares a benchmark file with a declared
  expected hash; agreement between servers alone cannot detect that all of
  them read the same wrong version.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

DEFAULT_GROUP_KEYS = ("speaker", "recording", "session", "room", "noise")
PURPOSES = ("train", "dev", "blind_test")


class LeakageError(ValueError):
    pass


class BenchmarkIntegrityError(ValueError):
    pass


def check_split_leakage(
    items: Iterable[Mapping],
    group_keys: Sequence[str] = DEFAULT_GROUP_KEYS,
) -> List[dict]:
    """Return every key value that appears in more than one split.

    Args:
        items: ``{"id": str, "split": str, "keys": {key: value | [values]}}``.
        group_keys: keys that must not cross splits.  Benchmarks with a device
            holdout add ``"device"`` here.

    Returns:
        list of ``{"key", "value", "splits", "items"}`` (empty when clean).
    """
    seen: Dict[tuple, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    for it in items:
        for k in group_keys:
            vals = (it.get("keys") or {}).get(k)
            if vals is None:
                continue
            for v in vals if isinstance(vals, (list, tuple, set)) else [vals]:
                seen[(k, v)][it["split"]].append(it["id"])
    leaks = []
    for (k, v), by_split in sorted(seen.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        if len(by_split) > 1:
            leaks.append({
                "key": k, "value": v,
                "splits": sorted(by_split),
                "items": sorted(i for ids in by_split.values() for i in ids),
            })
    return leaks


def assert_no_leakage(items: Iterable[Mapping], group_keys: Sequence[str] = DEFAULT_GROUP_KEYS) -> None:
    leaks = check_split_leakage(list(items), group_keys)
    if leaks:
        first = leaks[0]
        raise LeakageError(
            f"{len(leaks)} leaking key value(s); e.g. {first['key']}={first['value']!r} "
            f"in splits {first['splits']}"
        )


def assign_groups(
    items: Sequence[Mapping],
    ratios: Mapping[str, float],
    group_keys: Sequence[str] = DEFAULT_GROUP_KEYS,
    seed: int = 0,
) -> Dict[str, str]:
    """Assign whole connected groups of assets to splits.

    Items connected through any shared key value form one group (union–find).
    Groups are ordered deterministically (by a seeded hash) and each is placed
    in the split furthest below its target ratio (by item count).

    Returns:
        {item_id: split}
    """
    ids = [it["id"] for it in items]
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner: Dict[tuple, str] = {}
    for it in items:
        for k in group_keys:
            vals = (it.get("keys") or {}).get(k)
            if vals is None:
                continue
            for v in vals if isinstance(vals, (list, tuple, set)) else [vals]:
                if (k, v) in owner:
                    a, b = find(owner[(k, v)]), find(it["id"])
                    if a != b:
                        parent[a] = b
                else:
                    owner[(k, v)] = it["id"]

    groups: Dict[str, List[str]] = defaultdict(list)
    for i in ids:
        groups[find(i)].append(i)

    def _order(root: str) -> str:
        return hashlib.sha256(f"{seed}:{min(groups[root])}".encode()).hexdigest()

    total = float(sum(ratios.values()))
    target = {s: r / total * len(ids) for s, r in ratios.items()}
    count = {s: 0 for s in ratios}
    out: Dict[str, str] = {}
    for root in sorted(groups, key=lambda r: (-len(groups[r]), _order(r))):
        split = max(ratios, key=lambda s: (target[s] - count[s], s))
        for i in groups[root]:
            out[i] = split
        count[split] += len(groups[root])
    return out


class SessionRegistry:
    """Each real recording session has exactly one purpose (train/dev/blind_test)."""

    def __init__(self) -> None:
        self._purpose: Dict[str, str] = {}

    def register(self, session_id: str, purpose: str) -> None:
        if purpose not in PURPOSES:
            raise ValueError(f"purpose must be one of {PURPOSES}, got {purpose!r}")
        prev = self._purpose.get(session_id)
        if prev is not None and prev != purpose:
            raise LeakageError(
                f"session {session_id!r} already registered for {prev!r}; cannot also use it for {purpose!r}"
            )
        self._purpose[session_id] = purpose

    def purpose(self, session_id: str) -> Optional[str]:
        return self._purpose.get(session_id)

    def sessions(self, purpose: str) -> List[str]:
        return sorted(s for s, p in self._purpose.items() if p == purpose)


def verify_benchmark_manifest(path: str, expected_sha256: str) -> str:
    """Raise BenchmarkIntegrityError unless the file hashes to ``expected_sha256``."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    got = h.hexdigest()
    if got != expected_sha256:
        raise BenchmarkIntegrityError(
            f"benchmark manifest {path} hash {got[:12]}… != declared {expected_sha256[:12]}…"
        )
    return got
