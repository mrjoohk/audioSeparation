# Release gate: candidate → **INCONCLUSIVE**

> Rules status `proposed`: thresholds are not approved; verdict is advisory.

| Rule | Metric | vs | n | change | verdict | note |
| --- | --- | --- | --- | --- | --- | --- |
| wer_vs_fixed_baseline | wer | fixed_baseline | 0 | — | inconclusive | no common sessions |
| wer_vs_unprocessed | wer | unprocessed | 0 | — | inconclusive | no common sessions |
| der_vs_unprocessed | der | unprocessed | 24 | -25.042 | pass |  |

Regression (wer vs fixed_baseline, fail if degradation >= threshold, threshold 0.5 pp): **inconclusive**

| Condition | n | degradation (pp) | fails |
| --- | --- | --- | --- |
