# proxy-real test (held-out arrays)

Scenes: 24

| System | SI-SDRi (dB) | DER | DOA error (deg) |
| --- | --- | --- | --- |
| unprocessed | 0.00 | 1.199 | nan |
| M0_baseline | -1.97 | 0.965 | 38.4 |
| M1_augmented | -3.08 | 0.953 | 38.4 |
| M2_aug_coral | -3.51 | 0.948 | 38.4 |
| M3_coral_only | -2.45 | 0.949 | 38.4 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| M1_augmented-vs-unprocessed:si_sdri_db | 24 | -3.077 | [-4.523, -1.785] |
| M1_augmented-vs-unprocessed:der | 24 | -0.246 | [-0.362, -0.147] |
| M1_augmented-vs-M0_baseline:si_sdri_db | 24 | -1.108 | [-2.342, 0.097] |
| M1_augmented-vs-M0_baseline:der | 24 | -0.012 | [-0.026, 0.002] |
| M1_augmented-vs-M0_baseline:doa_err_deg | 24 | 0.000 | [0.000, 0.000] |
