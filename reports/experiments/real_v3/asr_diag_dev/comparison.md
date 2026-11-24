# AMI dev: WER metric diagnosis (oracle, cpWER)

Scenes: 160

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER | WER (gated) |
| --- | --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.743 | nan | 0.446 | 0.446 |
| v2-base | -0.05 | 0.530 | nan | 0.866 | 0.760 |
| v3-mix | 3.97 | 0.314 | nan | 0.699 | 0.580 |
| v3-real | 3.06 | 0.307 | nan | 0.605 | 0.540 |
| oracle | 127.65 | 0.145 | nan | 0.484 | 0.468 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| v3-mix-vs-unprocessed:si_sdri_db | 160 | 3.970 | [3.262, 4.735] |
| v3-mix-vs-unprocessed:der | 160 | -0.429 | [-0.461, -0.398] |
| v3-mix-vs-unprocessed:wer | 160 | 0.253 | [0.215, 0.294] |
| v3-mix-vs-unprocessed:wer_gated | 160 | 0.135 | [0.107, 0.162] |
| v3-mix-vs-unprocessed:cpwer | 160 | -0.120 | [-0.159, -0.078] |
| v3-mix-vs-unprocessed:cpwer_gated | 160 | -0.205 | [-0.240, -0.169] |
| v3-mix-vs-v2-base:si_sdri_db | 160 | 4.025 | [3.346, 4.741] |
| v3-mix-vs-v2-base:der | 160 | -0.216 | [-0.242, -0.191] |
| v3-mix-vs-v2-base:wer | 160 | -0.168 | [-0.210, -0.127] |
| v3-mix-vs-v2-base:wer_gated | 160 | -0.179 | [-0.213, -0.147] |
| v3-mix-vs-v2-base:cpwer | 160 | -0.210 | [-0.257, -0.163] |
| v3-mix-vs-v2-base:cpwer_gated | 160 | -0.211 | [-0.249, -0.173] |
| v3-mix-vs-v3-real:si_sdri_db | 160 | 0.915 | [0.364, 1.507] |
| v3-mix-vs-v3-real:der | 160 | 0.007 | [-0.011, 0.024] |
| v3-mix-vs-v3-real:wer | 160 | 0.094 | [0.059, 0.128] |
| v3-mix-vs-v3-real:wer_gated | 160 | 0.040 | [0.017, 0.063] |
| v3-mix-vs-v3-real:cpwer | 160 | 0.065 | [0.032, 0.099] |
| v3-mix-vs-v3-real:cpwer_gated | 160 | 0.009 | [-0.018, 0.035] |
| v3-mix-vs-oracle:si_sdri_db | 160 | -123.679 | [-125.029, -122.264] |
| v3-mix-vs-oracle:der | 160 | 0.169 | [0.146, 0.191] |
| v3-mix-vs-oracle:wer | 160 | 0.215 | [0.171, 0.260] |
| v3-mix-vs-oracle:wer_gated | 160 | 0.113 | [0.075, 0.146] |
| v3-mix-vs-oracle:cpwer | 160 | 0.358 | [0.306, 0.407] |
| v3-mix-vs-oracle:cpwer_gated | 160 | 0.282 | [0.233, 0.324] |
