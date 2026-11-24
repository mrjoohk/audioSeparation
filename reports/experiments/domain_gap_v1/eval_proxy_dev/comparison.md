# proxy-real dev

Scenes: 23

| System | SI-SDRi (dB) | DER | DOA error (deg) |
| --- | --- | --- | --- |
| unprocessed | 0.00 | 1.796 | nan |
| M0_baseline | 0.18 | 1.584 | 21.2 |
| M1_augmented | -0.92 | 1.543 | 21.2 |
| M2_aug_coral | -1.07 | 1.539 | 21.2 |
| M3_coral_only | -0.40 | 1.572 | 21.2 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| M2_aug_coral-vs-unprocessed:si_sdri_db | 23 | -1.066 | [-1.944, -0.305] |
| M2_aug_coral-vs-unprocessed:der | 23 | -0.258 | [-0.290, -0.229] |
| M2_aug_coral-vs-M0_baseline:si_sdri_db | 23 | -1.247 | [-1.961, -0.537] |
| M2_aug_coral-vs-M0_baseline:der | 23 | -0.046 | [-0.061, -0.031] |
| M2_aug_coral-vs-M0_baseline:doa_err_deg | 23 | 0.000 | [0.000, 0.000] |
| M2_aug_coral-vs-M1_augmented:si_sdri_db | 23 | -0.149 | [-0.984, 0.606] |
| M2_aug_coral-vs-M1_augmented:der | 23 | -0.005 | [-0.011, -0.000] |
| M2_aug_coral-vs-M1_augmented:doa_err_deg | 23 | 0.000 | [0.000, 0.000] |
