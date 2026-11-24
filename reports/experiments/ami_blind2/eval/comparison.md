# AMI blind2 (frozen candidate v1-cal)

Scenes: 800

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER | WER (gated) |
| --- | --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.771 | nan | 0.504 | 0.504 |
| v1-cal | -0.11 | 0.509 | nan | 0.870 | 0.756 |
| v1-base | 0.26 | 0.544 | nan | 0.880 | 0.745 |
| v2-cal | 0.12 | 0.512 | nan | 0.883 | 0.797 |
| v2-base | -0.23 | 0.557 | nan | 0.873 | 0.778 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| v1-cal-vs-unprocessed:si_sdri_db | 800 | -0.108 | [-0.300, 0.089] |
| v1-cal-vs-unprocessed:der | 800 | -0.262 | [-0.272, -0.252] |
| v1-cal-vs-unprocessed:wer | 800 | 0.365 | [0.343, 0.390] |
| v1-cal-vs-unprocessed:wer_gated | 800 | 0.252 | [0.236, 0.268] |
| v1-cal-vs-v1-base:si_sdri_db | 800 | -0.372 | [-0.576, -0.166] |
| v1-cal-vs-v1-base:der | 800 | -0.034 | [-0.044, -0.025] |
| v1-cal-vs-v1-base:wer | 800 | -0.011 | [-0.036, 0.015] |
| v1-cal-vs-v1-base:wer_gated | 800 | 0.011 | [-0.011, 0.030] |
| v1-cal-vs-v2-cal:si_sdri_db | 800 | -0.225 | [-0.405, -0.023] |
| v1-cal-vs-v2-cal:der | 800 | -0.003 | [-0.011, 0.004] |
| v1-cal-vs-v2-cal:wer | 800 | -0.014 | [-0.059, 0.025] |
| v1-cal-vs-v2-cal:wer_gated | 800 | -0.041 | [-0.072, -0.015] |
| v1-cal-vs-v2-base:si_sdri_db | 800 | 0.118 | [-0.087, 0.340] |
| v1-cal-vs-v2-base:der | 800 | -0.048 | [-0.057, -0.039] |
| v1-cal-vs-v2-base:wer | 800 | -0.003 | [-0.024, 0.020] |
| v1-cal-vs-v2-base:wer_gated | 800 | -0.022 | [-0.038, -0.006] |
