# AMI dev: v3 candidates vs v2 base

Scenes: 160

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER | WER (gated) |
| --- | --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.743 | nan | 0.446 | 0.446 |
| v2-base | -0.05 | 0.530 | nan | 0.866 | 0.760 |
| v3-mix | 3.97 | 0.314 | nan | 0.699 | 0.580 |
| v3-real | 3.06 | 0.307 | nan | 0.605 | 0.540 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| v3-real-vs-unprocessed:si_sdri_db | 160 | 3.055 | [2.207, 3.893] |
| v3-real-vs-unprocessed:der | 160 | -0.437 | [-0.468, -0.404] |
| v3-real-vs-unprocessed:wer | 160 | 0.160 | [0.131, 0.188] |
| v3-real-vs-unprocessed:wer_gated | 160 | 0.094 | [0.072, 0.117] |
| v3-real-vs-v2-base:si_sdri_db | 160 | 3.110 | [2.324, 3.919] |
| v3-real-vs-v2-base:der | 160 | -0.223 | [-0.248, -0.198] |
| v3-real-vs-v2-base:wer | 160 | -0.261 | [-0.302, -0.221] |
| v3-real-vs-v2-base:wer_gated | 160 | -0.220 | [-0.253, -0.188] |
| v3-real-vs-v3-mix:si_sdri_db | 160 | -0.915 | [-1.507, -0.364] |
| v3-real-vs-v3-mix:der | 160 | -0.007 | [-0.024, 0.011] |
| v3-real-vs-v3-mix:wer | 160 | -0.094 | [-0.128, -0.059] |
| v3-real-vs-v3-mix:wer_gated | 160 | -0.040 | [-0.063, -0.017] |
