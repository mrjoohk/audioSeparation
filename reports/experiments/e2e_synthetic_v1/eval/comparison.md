# e2e_synthetic_v1: synthetic held-out test

Scenes: 30

| System | SI-SDRi (dB) | DER | DOA error (deg) |
| --- | --- | --- | --- |
| unprocessed | 0.00 | 1.484 | nan |
| baseline_ds | -4.76 | 1.468 | 46.0 |
| candidate_mask | 0.77 | 1.276 | 46.0 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| candidate_mask-vs-unprocessed:si_sdri_db | 30 | 0.772 | [0.368, 1.237] |
| candidate_mask-vs-unprocessed:der | 30 | -0.209 | [-0.248, -0.170] |
| candidate_mask-vs-baseline_ds:si_sdri_db | 30 | 5.535 | [4.785, 6.222] |
| candidate_mask-vs-baseline_ds:der | 30 | -0.193 | [-0.238, -0.148] |
| candidate_mask-vs-baseline_ds:doa_err_deg | 30 | 0.000 | [0.000, 0.000] |
