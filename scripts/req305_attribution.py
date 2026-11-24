"""REQ-305 downstream WER table and factor attribution from saved per-scene results.

Criterion (design §6.2, fixed before any run): the gap-reduction model's WER must be
at least 3.0 %p (absolute) below the fixed baseline model's WER, with the paired 95 %
CI upper bound < 0; fewer than 20 sessions -> judgement withheld.  Factor attribution
follows the training recipes, which differ by one factor at a time:

  augmentation (domain randomisation + device/noise augmentation): robust - base
  calibration (RT60 targets from AMI dev):                          cal - robust
  total (gap-reduction candidate):                                   cal - base

"Mixed data" (synthetic + real curriculum) has no real-data training run, so it is
reported as not measured.  No new inference is run; inputs are the comparison.json
files written by scripts/run_real_data_experiments.py.

    python scripts/req305_attribution.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evaluation.compare import paired_bootstrap  # noqa: E402

EXP = ROOT / "reports" / "experiments"
OUT = EXP / "req305"
SETS = [
    # (label, path, real-world?, unseen?, WER field)
    ("AMI dev v1", "real_v1/eval_ami_dev", True, False, "wer"),
    ("AMI blind_test v1", "real_v1/eval_ami_blind", True, True, "wer"),
    ("AMI dev v2", "real_v2/eval_ami_dev", True, False, "wer"),
    ("LibriSpeech test v1 (simulated rooms)", "real_v1/eval_asr_librispeech", False, True, "wer"),
    ("LibriSpeech test v2 (simulated rooms)", "real_v2/eval_asr_librispeech", False, True, "wer"),
    # dominance-gated word-level ASR (rule fixed before results; evaluation.asr.gate_segments)
    ("AMI dev v1, gated", "real_v1/eval_ami_dev_gated", True, False, "wer_gated"),
    ("AMI dev v2, gated", "real_v2/eval_ami_dev_gated", True, False, "wer_gated"),
    ("LibriSpeech test v1, gated", "real_v1/eval_asr_librispeech_gated", False, True, "wer_gated"),
    ("LibriSpeech test v2, gated", "real_v2/eval_asr_librispeech_gated", False, True, "wer_gated"),
]
FACTORS = [("augmentation", "robust", "base"), ("calibration", "cal", "robust"), ("total (cal vs base)", "cal", "base")]
THRESHOLD_PP = -3.0
MIN_SESSIONS = 20


def session_of(scene_id: str) -> str:
    return scene_id.rsplit("_", 1)[0]


def table_for(path: Path, field: str = "wer") -> dict:
    rows = json.loads((path / "comparison.json").read_text(encoding="utf-8"))["rows"]
    wer = {(r["scene_id"], r["system"]): r[field] for r in rows if r.get(field) is not None}
    systems = sorted({s for _, s in wer})
    scenes = sorted({i for i, _ in wer})
    means = {s: sum(wer[(i, s)] for i in scenes) / len(scenes) for s in systems}
    out = {"n_scenes": len(scenes), "n_sessions": len({session_of(i) for i in scenes}),
           "wer_field": field, "mean_wer": means, "factors": {}}
    for name, a, b in FACTORS:
        if a in systems and b in systems:
            diffs = [100.0 * (wer[(i, a)] - wer[(i, b)]) for i in scenes]
            m, lo, hi = paired_bootstrap(diffs)
            out["factors"][name] = {"delta_pp": m, "ci95_pp": [lo, hi]}
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"criterion": {"threshold_pp": THRESHOLD_PP, "ci_upper_below": 0.0, "min_sessions": MIN_SESSIONS,
                            "baseline": "base", "candidate": "cal"}, "sets": {}}
    lines = ["# REQ-305 하위 태스크 WER 요인 기여표", "",
             "`scripts/req305_attribution.py`가 저장된 장면별 결과에서 만든다(새 추론 없음). WER은 Whisper small.en, 단위 %p.",
             "합격 조건(설계 §6.2, 실행 전 고정): 후보(cal)가 기준(base)보다 3.0 %p 이상 낮고 쌍 비교 95 % CI 상한 < 0. 세션 20개 미만이면 판정 보류.",
             "",
             "| 평가 세트 | 실측 | 장면/세션 | 원음 | base | robust | cal | 증강 (robust−base) | 보정 (cal−robust) | 합계 (cal−base) | 판정 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for label, rel, real, unseen, field in SETS:
        p = EXP / rel
        if not (p / "comparison.json").exists():
            continue
        t = table_for(p, field)
        tot = t["factors"].get("total (cal vs base)")
        if tot is None:
            verdict = "해당 없음"
        else:
            passed = tot["delta_pp"] <= THRESHOLD_PP and tot["ci95_pp"][1] < 0
            verdict = "충족" if passed else "미충족"
            if real and t["n_sessions"] < MIN_SESSIONS:
                verdict += f" (세션 {t['n_sessions']} < {MIN_SESSIONS}: 보류)"
            if not real:
                verdict += " (실측 아님: 판정 근거 아님)"
        t.update({"real_world": real, "unseen": unseen, "verdict": verdict})
        result["sets"][label] = t
        mw = t["mean_wer"]

        def f(name):
            x = t["factors"].get(name)
            return "—" if x is None else f"{x['delta_pp']:+.1f} ({x['ci95_pp'][0]:+.1f}~{x['ci95_pp'][1]:+.1f})"

        def w(s):
            return f"{100 * mw[s]:.1f}" if s in mw else "—"
        lines.append(f"| {label} | {'예' if real else '아니오'} | {t['n_scenes']}/{t['n_sessions']} | {w('unprocessed')} | "
                     f"{w('base')} | {w('robust')} | {w('cal')} | {f('augmentation')} | {f('calibration')} | "
                     f"{f('total (cal vs base)')} | {verdict} |")
    lines += ["", "* 혼합 자료(합성+실측 커리큘럼) 요인은 실측 학습 실행이 없어 측정하지 않았다.",
              "* LibriSpeech 시험은 실음성을 시뮬레이션 방에서 렌더한 것이라 실측 판정 근거가 아니다.",
              "* 'gated'는 단어 단위 Whisper 출력에서 자기 스트림의 화자 구간(±0.1 s) 밖 단어를 버린 WER이다(실행 전 고정 규칙, 모든 시스템에 동일 적용, 원음은 스트림이 하나라 변화 없음).",
              "* 단어 타임스탬프 모드는 Whisper 디코딩 자체를 바꾸므로 gated 행의 원음 WER이 일반 행과 다르다. 비교는 같은 행 안에서만 한다.",
              "* LibriSpeech 시험의 '세션'은 장면 ID 접두어로 센 것이라 실측 세션 수와 의미가 다르다."]
    (OUT / "attribution.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "attribution.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")          # Korean Windows console defaults to cp949
    print("\n".join(lines))


if __name__ == "__main__":
    main()
