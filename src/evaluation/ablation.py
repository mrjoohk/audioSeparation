"""
Ablation / attribution dashboard (REQ-404; design §6.3).

Input: run name → metric means, with a "base" run and runs that remove one or
more factors, named "-reverb", "-motion", "-adaptation+-reverb" (factors joined
by "+").  Output: per-factor impact coefficients (percent change of each metric
when the factor is removed), pairwise interaction terms when the combined
ablation exists, a cross-metric correlation of the deltas, and a report in
Markdown + PDF.

Impact (%) = (ablated − base) / |base| × 100.  For metrics where lower is
better (WER, DER) a positive impact means removing the factor hurt.
Interaction(a, b) = Δ(a+b) − Δa − Δb (in metric units).
"""
from __future__ import annotations

import itertools
import json
import math
import os
from typing import Dict, List, Mapping, Optional

import numpy as np

LOWER_IS_BETTER = {"wer", "der", "doa_err_deg"}


def _factors(name: str) -> List[str]:
    return sorted(p.lstrip("-") for p in name.split("+") if p.startswith("-"))


def attribution(runs: Mapping[str, Mapping[str, float]], metrics: Optional[List[str]] = None) -> dict:
    if "base" not in runs:
        raise ValueError("runs need a 'base' entry")
    base = runs["base"]
    metrics = metrics or sorted(base)
    singles = {name: _factors(name)[0] for name in runs if name != "base" and len(_factors(name)) == 1}
    impact = {}
    for name, fac in sorted(singles.items(), key=lambda x: x[1]):
        row = {}
        for m in metrics:
            if m in runs[name] and m in base:
                d = runs[name][m] - base[m]
                row[m] = {"delta": d, "impact_pct": 100.0 * d / abs(base[m]) if base[m] else float("nan")}
        impact[fac] = row
    inter = {}
    by_set = {tuple(_factors(n)): n for n in runs if n != "base"}
    for a, b in itertools.combinations(sorted(impact), 2):
        name = by_set.get(tuple(sorted([a, b])))
        if not name:
            continue
        inter[f"{a}+{b}"] = {m: (runs[name][m] - base[m]) - impact[a][m]["delta"] - impact[b][m]["delta"]
                             for m in metrics if m in runs[name] and m in impact[a] and m in impact[b]}
    corr = {}
    for m1, m2 in itertools.combinations(metrics, 2):
        x = [impact[f][m1]["delta"] for f in impact if m1 in impact[f] and m2 in impact[f]]
        y = [impact[f][m2]["delta"] for f in impact if m1 in impact[f] and m2 in impact[f]]
        if len(x) >= 3 and np.std(x) > 0 and np.std(y) > 0:
            corr[f"{m1}~{m2}"] = float(np.corrcoef(x, y)[0, 1])
    missing = [f for f in impact if any(m not in impact[f] for m in metrics)]
    return {"metrics": metrics, "base": dict(base), "impact": impact, "interactions": inter,
            "delta_correlation": corr, "factors_missing_metrics": missing}


def write_dashboard(att: Mapping, out_dir: str, title: str = "Ablation dashboard") -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    metrics, factors = att["metrics"], sorted(att["impact"])
    lines = [f"# {title}", "", "Impact = (ablated − base) / |base| × 100 %. Lower-is-better metrics: "
             + ", ".join(sorted(LOWER_IS_BETTER & set(metrics))), "",
             "| Factor removed | " + " | ".join(metrics) + " |", "| --- |" + " --- |" * len(metrics)]
    for f in factors:
        cells = []
        for m in metrics:
            v = att["impact"][f].get(m)
            cells.append("—" if v is None else f"{v['impact_pct']:+.1f} %")
        lines.append(f"| {f} | " + " | ".join(cells) + " |")
    if att["interactions"]:
        lines += ["", "| Interaction | " + " | ".join(metrics) + " |", "| --- |" + " --- |" * len(metrics)]
        for k, v in att["interactions"].items():
            lines.append(f"| {k} | " + " | ".join(f"{v.get(m, float('nan')):+.3f}" for m in metrics) + " |")
    if att["delta_correlation"]:
        lines += ["", "Cross-metric correlation of deltas: "
                  + ", ".join(f"{k} = {v:+.2f}" for k, v in att["delta_correlation"].items())]
    md = os.path.join(out_dir, "ablation.md")
    with open(md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(out_dir, "ablation.json"), "w", encoding="utf-8") as fh:
        json.dump(att, fh, indent=1)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    pdf = os.path.join(out_dir, "ablation.pdf")
    with PdfPages(pdf) as pp:
        fig, ax = plt.subplots(figsize=(8, 0.6 + 0.5 * max(1, len(factors))))
        data = np.array([[att["impact"][f].get(m, {}).get("impact_pct", np.nan) for m in metrics] for f in factors])
        im = ax.imshow(data, cmap="RdBu_r", vmin=-np.nanmax(np.abs(data)) if data.size else -1,
                       vmax=np.nanmax(np.abs(data)) if data.size else 1, aspect="auto")
        ax.set_xticks(range(len(metrics)), metrics)
        ax.set_yticks(range(len(factors)), [f"-{f}" for f in factors])
        for i in range(len(factors)):
            for j in range(len(metrics)):
                if not np.isnan(data[i, j]):
                    ax.text(j, i, f"{data[i, j]:+.1f}%", ha="center", va="center", fontsize=9)
        ax.set_title(f"{title}: impact of removing each factor")
        fig.colorbar(im, ax=ax, label="% change vs base")
        fig.tight_layout()
        pp.savefig(fig)
        plt.close(fig)
    return {"markdown": md, "pdf": pdf}
