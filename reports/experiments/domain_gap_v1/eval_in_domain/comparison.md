# in-domain (source test)

Scenes: 24

| System | SI-SDRi (dB) | DER | DOA error (deg) |
| --- | --- | --- | --- |
| unprocessed | 0.00 | 1.807 | nan |
| M0_baseline | 0.52 | 1.543 | 36.4 |
| M1_augmented | 0.35 | 1.496 | 36.4 |
| M2_aug_coral | 0.25 | 1.477 | 36.4 |
| M3_coral_only | 0.40 | 1.537 | 36.4 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| M1_augmented-vs-unprocessed:si_sdri_db | 24 | 0.351 | [-0.031, 0.823] |
| M1_augmented-vs-unprocessed:der | 24 | -0.311 | [-0.352, -0.269] |
| M1_augmented-vs-M0_baseline:si_sdri_db | 24 | -0.172 | [-0.271, -0.084] |
| M1_augmented-vs-M0_baseline:der | 24 | -0.047 | [-0.063, -0.033] |
| M1_augmented-vs-M0_baseline:doa_err_deg | 24 | 0.000 | [0.000, 0.000] |
