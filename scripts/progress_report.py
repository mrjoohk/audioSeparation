"""
Render progress bars from reports/progress/implementation_roadmap.md (PROJECT_RULES §진척 보고).

Counts "- [x]" (done) and "- [ ]" (open) items under each "### N. <title>" heading.
Open items whose text contains "차단" are reported as blocked.

Usage:
    .venv/Scripts/python.exe scripts/progress_report.py            # print bars
    .venv/Scripts/python.exe scripts/progress_report.py --table     # also refresh the summary table in the roadmap
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROADMAP = Path(__file__).resolve().parents[1] / "reports" / "progress" / "implementation_roadmap.md"
WIDTH = 20


def bar(done: int, total: int) -> str:
    frac = done / total if total else 0.0
    n = round(frac * WIDTH)
    return f"[{'█' * n}{'░' * (WIDTH - n)}] {round(frac * 100):3d}%"


def parse(text: str):
    stages = []
    cur = None
    for line in text.splitlines():
        m = re.match(r"^### (\d+)\. (.+?)(?: — .*)?$", line)
        if m:
            cur = {"n": int(m.group(1)), "title": m.group(2).strip(), "done": 0, "open": 0, "blocked": 0}
            stages.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("- [x]"):
            cur["done"] += 1
        elif line.startswith("- [ ]"):
            cur["open"] += 1
            if "차단" in line:
                cur["blocked"] += 1
    return stages


def status(s) -> str:
    total = s["done"] + s["open"]
    if s["open"] == 0:
        return "완료"
    if s["open"] == s["blocked"]:
        return "완료(차단 항목 제외)"
    if s["done"] == 0:
        return "대기"
    return "진행 중"


def render(stages) -> str:
    done = sum(s["done"] for s in stages)
    total = sum(s["done"] + s["open"] for s in stages)
    blocked = sum(s["blocked"] for s in stages)
    w = max(len(s["title"]) for s in stages) + 4
    lines = [f"{'전체':<{w}} {bar(done, total)}  {done}/{total}  (차단 {blocked})", ""]
    for s in stages:
        t = s["done"] + s["open"]
        name = f"{s['n']}. {s['title']}"
        extra = f", 차단 {s['blocked']}" if s["blocked"] else ""
        lines.append(f"{name:<{w}} {bar(s['done'], t)}  {s['done']}/{t}  {status(s)}{extra}")
    return "\n".join(lines)


def refresh_table(text: str, stages) -> str:
    by_n = {s["n"]: s for s in stages}

    def repl(m):
        n = int(m.group(1))
        s = by_n.get(n)
        if not s:
            return m.group(0)
        return f"{m.group(0).rsplit('|', 2)[0]}| {s['done']}/{s['done'] + s['open']} |"

    return re.sub(r"^\| (\d+) \|.*\| \d+/\d+ \|$", repl, text, flags=re.M)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", action="store_true")
    a = ap.parse_args()
    text = ROADMAP.read_text(encoding="utf-8")
    stages = parse(text)
    if a.table:
        ROADMAP.write_text(refresh_table(text, stages), encoding="utf-8")
    sys.stdout.buffer.write((render(stages) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
