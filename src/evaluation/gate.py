"""
Release / candidate decision engine (REQ-405; audit F-06; design §6.2).

Rules come from ``configs/decision_rules.yaml``.  Inputs are per-session
metrics for each system on the same sessions, optionally with a condition
label per session (room type, SNR band, device …).

Verdict per rule: "pass" / "fail" / "inconclusive"; overall "fail" if any rule
fails, else "inconclusive" if any rule is inconclusive, else "pass".  While the
rules file has ``status: proposed`` the verdict is marked advisory.

Boundary conventions (fixed here, see design §6.2):
* comparison rules pass when change <= max_change (equality passes);
* regression fails when degradation >= max_condition_degradation_pp
  (REQ-405 acceptance: a 0.5 % WER regression must fail).
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Mapping, Optional, Sequence

import numpy as np

from evaluation.compare import paired_bootstrap


def load_rules(path: str) -> dict:
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _change(kind: str, cand: float, ref: float) -> Optional[float]:
    if kind == "absolute_pp":
        return (cand - ref) * 100.0
    if kind == "relative":
        return None if ref == 0 else (cand - ref) / ref
    raise ValueError(kind)


def evaluate_rule(rule: Mapping, sessions: Mapping[str, Mapping[str, Mapping[str, float]]],
                  candidate: str, unc: Mapping) -> dict:
    """sessions: session_id -> system -> metric -> value (rates in [0, 1])."""
    metric, ref_sys = rule["metric"], rule["reference"]
    common = [s for s, v in sessions.items() if candidate in v and ref_sys in v
              and metric in v[candidate] and metric in v[ref_sys]]
    out = {"id": rule["id"], "metric": metric, "reference": ref_sys, "n_sessions": len(common)}
    if not common:
        out.update(verdict="inconclusive", reason="no common sessions")
        return out
    c = float(np.mean([sessions[s][candidate][metric] for s in common]))
    r = float(np.mean([sessions[s][ref_sys][metric] for s in common]))
    out.update(candidate_mean=c, reference_mean=r)
    if r == 0:
        zr = rule.get("zero_reference", "candidate_must_be_zero")
        if zr == "candidate_must_be_zero":
            ok = c == 0
        elif zr.startswith("absolute_pp_max_"):
            ok = (c - r) * 100 <= float(zr.rsplit("_", 1)[1])
        else:
            raise ValueError(zr)
        out.update(change=None, verdict="pass" if ok else "fail", reason=f"zero reference ({zr})")
        return out
    change = _change(rule["kind"], c, r)
    out["change"] = change
    ok = change <= float(rule["max_change"])
    if len(common) < int(unc.get("min_sessions", 0)):
        out.update(verdict="inconclusive", reason=f"{len(common)} < min_sessions {unc['min_sessions']}")
        return out
    diffs = [sessions[s][candidate][metric] - sessions[s][ref_sys][metric] for s in common]
    mean, lo, hi = paired_bootstrap(diffs, n=int(unc.get("n_resamples", 2000)),
                                    confidence=float(unc.get("confidence", 0.95)))
    out["paired_diff_ci95"] = [lo, hi]
    if ok and unc.get("require_ci_upper_below_zero") and not hi < 0:
        out.update(verdict="inconclusive", reason="improvement not significant (CI upper >= 0)")
        return out
    out["verdict"] = "pass" if ok else "fail"
    return out


def evaluate_regression(reg: Mapping, sessions, conditions: Mapping[str, str], candidate: str) -> dict:
    metric, ref_sys = reg["metric"], reg["reference"]
    thr = float(reg["max_condition_degradation_pp"])
    by_cond: Dict[str, List[float]] = {}
    for s, v in sessions.items():
        if candidate in v and ref_sys in v and metric in v[candidate] and metric in v[ref_sys]:
            by_cond.setdefault(conditions.get(s, "all"), []).append(
                (v[candidate][metric] - v[ref_sys][metric]) * 100.0)
    rows = []
    worst = None
    for cond, d in sorted(by_cond.items()):
        deg = float(np.mean(d))
        failed = deg >= thr
        rows.append({"condition": cond, "n_sessions": len(d), "degradation_pp": deg, "fails": failed})
        worst = deg if worst is None else max(worst, deg)
    verdict = "inconclusive" if not rows else ("fail" if any(r["fails"] for r in rows) else "pass")
    return {"metric": metric, "reference": ref_sys, "threshold_pp": thr, "rule": "fail if degradation >= threshold",
            "conditions": rows, "worst_degradation_pp": worst, "verdict": verdict}


def decide(rules: Mapping, sessions, candidate: str, conditions: Optional[Mapping[str, str]] = None) -> dict:
    unc = rules.get("uncertainty", {})
    results = [evaluate_rule(r, sessions, candidate, unc) for r in rules.get("comparisons", [])]
    reg = evaluate_regression(rules["regression"], sessions, conditions or {}, candidate) \
        if rules.get("regression") else None
    verdicts = [r["verdict"] for r in results] + ([reg["verdict"]] if reg else [])
    overall = "fail" if "fail" in verdicts else ("inconclusive" if "inconclusive" in verdicts else "pass")
    return {
        "candidate": candidate,
        "verdict": overall,
        "advisory": rules.get("status") != "approved",
        "rules_version": rules.get("version"), "rules_status": rules.get("status"),
        "comparisons": results, "regression": reg,
    }


def report_markdown(decision: Mapping) -> str:
    lines = [f"# Release gate: {decision['candidate']} → **{decision['verdict'].upper()}**", ""]
    if decision["advisory"]:
        lines += [f"> Rules status `{decision['rules_status']}`: thresholds are not approved; verdict is advisory.", ""]
    lines += ["| Rule | Metric | vs | n | change | verdict | note |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in decision["comparisons"]:
        ch = r.get("change")
        lines.append(f"| {r['id']} | {r['metric']} | {r['reference']} | {r['n_sessions']} | "
                     f"{'—' if ch is None else f'{ch:.3f}'} | {r['verdict']} | {r.get('reason', '')} |")
    reg = decision.get("regression")
    if reg:
        lines += ["", f"Regression ({reg['metric']} vs {reg['reference']}, {reg['rule']}, threshold {reg['threshold_pp']} pp): "
                  f"**{reg['verdict']}**", "", "| Condition | n | degradation (pp) | fails |", "| --- | --- | --- | --- |"]
        for c in reg["conditions"]:
            lines.append(f"| {c['condition']} | {c['n_sessions']} | {c['degradation_pp']:.3f} | {c['fails']} |")
    return "\n".join(lines) + "\n"
