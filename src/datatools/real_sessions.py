"""
Real-recording session registry (audit F-03, F-04; design §6.1).

The registry is a CSV with one row per recording session.  This module
validates it, assigns train / dev / blind_test splits at session granularity
(sessions sharing a room or speaker stay together), reports which tasks have
ground truth (valid denominators), and guards blind_test access.

Required columns (design §6.1):
    session_id, source, license_scope, consent_verified, room_id, device_id,
    mic_layout, sync_method, device_dsp, speakers, has_ref_wave, has_transcript,
    has_speaker_timeline, has_position, annotation_qc_sample, split
``speakers`` is a ';'-separated list of speaker IDs.
"""
from __future__ import annotations

import csv
import hashlib
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from datatools.splits import (
    LeakageError,
    SessionRegistry,
    assign_groups,
    check_split_leakage,
)

REQUIRED_COLUMNS = (
    "session_id", "source", "license_scope", "consent_verified", "room_id", "device_id",
    "mic_layout", "sync_method", "device_dsp", "speakers", "has_ref_wave", "has_transcript",
    "has_speaker_timeline", "has_position", "annotation_qc_sample", "split",
)
BOOL_COLUMNS = ("consent_verified", "has_ref_wave", "has_transcript", "has_speaker_timeline",
                "has_position", "annotation_qc_sample")
SPLITS = ("train", "dev", "blind_test")
TASK_LABELS = {
    "separation": "has_ref_wave",
    "asr": "has_transcript",
    "diarization": "has_speaker_timeline",
    "localization": "has_position",
}
DEFAULT_GROUP_KEYS = ("room", "speaker")


class RegistryError(ValueError):
    def __init__(self, problems: List[str]):
        self.problems = problems
        super().__init__(f"{len(problems)} registry problem(s): " + "; ".join(problems[:5]))


def _bool(v: str) -> Optional[bool]:
    t = str(v).strip().lower()
    if t in ("true", "1", "yes", "y"):
        return True
    if t in ("false", "0", "no", "n", ""):
        return False
    return None


def validate_rows(rows: Sequence[Mapping[str, str]]) -> List[dict]:
    """Validate and normalise registry rows; raise RegistryError listing all problems."""
    problems: List[str] = []
    out: List[dict] = []
    seen = set()
    for i, r in enumerate(rows):
        missing = [c for c in REQUIRED_COLUMNS if c not in r]
        if missing:
            problems.append(f"row {i}: missing columns {missing}")
            continue
        row = {k: (str(v).strip() if v is not None else "") for k, v in r.items()}
        sid = row["session_id"]
        if not sid:
            problems.append(f"row {i}: empty session_id")
        elif sid in seen:
            problems.append(f"row {i}: duplicate session_id {sid!r}")
        seen.add(sid)
        for c in BOOL_COLUMNS:
            b = _bool(row[c])
            if b is None:
                problems.append(f"{sid}: {c}={row[c]!r} is not a boolean")
            row[c] = bool(b)
        if row["device_dsp"] not in ("on", "off", "unknown"):
            problems.append(f"{sid}: device_dsp must be on/off/unknown")
        if not row["license_scope"]:
            problems.append(f"{sid}: license_scope is empty")
        if row["split"] and row["split"] not in SPLITS:
            problems.append(f"{sid}: split {row['split']!r} not in {SPLITS}")
        if row["split"] and not row["consent_verified"]:
            problems.append(f"{sid}: split assigned but consent_verified is false")
        row["speakers"] = [s for s in row["speakers"].split(";") if s]
        out.append(row)
    if problems:
        raise RegistryError(problems)
    return out


def load_registry(path: str) -> List[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return validate_rows(list(csv.DictReader(fh)))


def write_registry(rows: Iterable[Mapping], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(REQUIRED_COLUMNS))
        w.writeheader()
        for r in rows:
            d = {c: r.get(c, "") for c in REQUIRED_COLUMNS}
            d["speakers"] = ";".join(r.get("speakers", [])) if isinstance(r.get("speakers"), list) else r.get("speakers", "")
            for c in BOOL_COLUMNS:
                d[c] = "true" if r.get(c) else "false"
            w.writerow(d)


def _items(rows):
    return [{"id": r["session_id"], "split": r.get("split") or None,
             "keys": {"room": r["room_id"], "speaker": list(r["speakers"])}} for r in rows]


def assign_session_splits(
    rows: List[dict],
    ratios: Mapping[str, float],
    group_keys: Sequence[str] = DEFAULT_GROUP_KEYS,
    seed: int = 0,
) -> List[dict]:
    """Assign splits to consented sessions without one; keep existing assignments.

    Sessions linked through a shared room or speaker form one group.  A group
    that already contains an assigned session inherits that split; a group with
    two different existing splits is a leakage error.
    """
    eligible = [r for r in rows if r["consent_verified"]]
    items = _items(eligible)
    groups = assign_groups([{"id": it["id"], "keys": it["keys"]} for it in items],
                           ratios, group_keys=group_keys, seed=seed)
    # ``groups`` gives a provisional split per session (whole components share one).
    # Recompute the components to honour pre-assigned splits.
    comp: Dict[str, List[str]] = {}
    parent = {it["id"]: it["id"] for it in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner = {}
    for it in items:
        for k in group_keys:
            vals = it["keys"].get(k)
            for v in vals if isinstance(vals, list) else [vals]:
                if v is None:
                    continue
                if (k, v) in owner:
                    a, b = find(owner[(k, v)]), find(it["id"])
                    if a != b:
                        parent[a] = b
                else:
                    owner[(k, v)] = it["id"]
    for it in items:
        comp.setdefault(find(it["id"]), []).append(it["id"])
    by_id = {r["session_id"]: r for r in rows}
    for members in comp.values():
        fixed = {by_id[m]["split"] for m in members if by_id[m]["split"]}
        if len(fixed) > 1:
            raise LeakageError(f"sessions {sorted(members)} are linked but pre-assigned to {sorted(fixed)}")
        target = fixed.pop() if fixed else groups[members[0]]
        for m in members:
            by_id[m]["split"] = target
    leaks = check_split_leakage([i for i in _items(rows) if i["split"]], group_keys)
    if leaks:
        raise LeakageError(f"leakage after assignment: {leaks[0]}")
    return rows


def build_session_registry(rows: Iterable[Mapping]) -> SessionRegistry:
    reg = SessionRegistry()
    for r in rows:
        if r.get("split"):
            reg.register(r["session_id"], r["split"])
    return reg


def label_availability(rows: Iterable[Mapping], split: Optional[str] = None) -> Dict[str, dict]:
    """Valid denominators per task: sessions that have the needed ground truth."""
    rows = [r for r in rows if split is None or r.get("split") == split]
    out = {}
    for task, col in TASK_LABELS.items():
        have = [r["session_id"] for r in rows if r.get(col)]
        out[task] = {"n_sessions": len(rows), "n_with_labels": len(have),
                     "excluded": sorted(r["session_id"] for r in rows if not r.get(col))}
    return out


class BlindTestGuard:
    """blind_test is opened only for a frozen candidate (design §4.7, F-04).

    Training, calibration, failure analysis and model selection use train/dev.
    ``freeze`` records the candidate checkpoint hash; ``open`` refuses blind
    sessions for anything else and logs every access.
    """

    def __init__(self, rows: Iterable[Mapping]):
        self._rows = list(rows)
        self.frozen: Optional[str] = None
        self.access_log: List[dict] = []

    def freeze(self, checkpoint_sha256: str) -> None:
        if self.frozen is not None and self.frozen != checkpoint_sha256:
            raise PermissionError("a different candidate is already frozen for blind evaluation")
        self.frozen = checkpoint_sha256

    def open(self, purpose: str, checkpoint_sha256: Optional[str] = None) -> List[str]:
        if purpose not in SPLITS:
            raise ValueError(purpose)
        if purpose == "blind_test":
            if self.frozen is None or checkpoint_sha256 != self.frozen:
                raise PermissionError("blind_test is only available to the frozen candidate")
        sessions = sorted(r["session_id"] for r in self._rows if r.get("split") == purpose)
        self.access_log.append({"purpose": purpose, "checkpoint": checkpoint_sha256, "n": len(sessions)})
        return sessions


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
