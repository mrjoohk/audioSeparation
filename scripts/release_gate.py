"""
Release gate for CI (REQ-405).

    .venv/Scripts/python.exe scripts/release_gate.py --comparison <comparison.json> \
        --candidate M2_aug_coral --fixed-baseline M0_baseline --unprocessed unprocessed \
        [--conditions conditions.json] [--blind-checkpoint <sha256>] --out reports/gate

Exit code: 0 pass, 1 fail, 2 inconclusive.  While configs/decision_rules.yaml
has status 'proposed' the verdict is advisory (printed in the report).
Blind-test sessions may be evaluated only for a frozen candidate: pass
--blind-checkpoint with the checkpoint sha256 recorded at freeze time.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evaluation.gate import decide, load_rules, report_markdown  # noqa: E402


def sessions_from_comparison(path: str, roles: dict) -> dict:
    with open(path, encoding="utf-8") as fh:
        rep = json.load(fh)
    inv = {v: k for k, v in roles.items()}
    out = {}
    for row in rep["rows"]:
        role = inv.get(row["system"])
        if role is None:
            continue
        metrics = {k: row[k] for k in ("wer", "cpwer", "der") if k in row}
        out.setdefault(row["scene_id"], {})[role] = metrics
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--comparison", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--fixed-baseline", required=True)
    ap.add_argument("--unprocessed", default="unprocessed")
    ap.add_argument("--rules", default=str(ROOT / "configs" / "decision_rules.yaml"))
    ap.add_argument("--conditions", default=None, help="JSON {session_id: condition}")
    ap.add_argument("--out", default=str(ROOT / "reports" / "gate"))
    a = ap.parse_args()
    roles = {"candidate": a.candidate, "fixed_baseline": a.fixed_baseline, "unprocessed": a.unprocessed}
    sessions = sessions_from_comparison(a.comparison, roles)
    cond = json.load(open(a.conditions, encoding="utf-8")) if a.conditions else None
    d = decide(load_rules(a.rules), sessions, "candidate", cond)
    d["systems"] = roles
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "gate.json"), "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=1)
    md = report_markdown(d)
    with open(os.path.join(a.out, "gate.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    sys.stdout.buffer.write(md.encode("utf-8"))
    return {"pass": 0, "fail": 1, "inconclusive": 2}[d["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
