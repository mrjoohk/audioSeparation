# AMI blind3 (frozen candidate v3-mix)

Scenes: 640

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER | WER (gated) |
| --- | --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.774 | nan | 0.508 | 0.508 |
| v3-mix | 3.02 | 0.364 | nan | 0.798 | 0.648 |
| v2-base | -0.34 | 0.583 | nan | 0.910 | 0.818 |
| v3-real | 2.83 | 0.323 | nan | 0.687 | 0.620 |
| v2-cal | 0.07 | 0.521 | nan | 0.900 | 0.814 |
| v1-base | 0.39 | 0.563 | nan | 0.883 | 0.755 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| v3-mix-vs-unprocessed:si_sdri_db | 640 | 3.015 | [2.747, 3.274] |
| v3-mix-vs-unprocessed:der | 640 | -0.411 | [-0.425, -0.396] |
| v3-mix-vs-unprocessed:wer | 640 | 0.289 | [0.265, 0.313] |
| v3-mix-vs-unprocessed:wer_gated | 640 | 0.140 | [0.120, 0.158] |
| v3-mix-vs-v2-base:si_sdri_db | 640 | 3.357 | [3.070, 3.641] |
| v3-mix-vs-v2-base:der | 640 | -0.219 | [-0.231, -0.206] |
| v3-mix-vs-v2-base:wer | 640 | -0.113 | [-0.133, -0.092] |
| v3-mix-vs-v2-base:wer_gated | 640 | -0.170 | [-0.186, -0.154] |
| v3-mix-vs-v3-real:si_sdri_db | 640 | 0.183 | [-0.118, 0.495] |
| v3-mix-vs-v3-real:der | 640 | 0.041 | [0.027, 0.053] |
| v3-mix-vs-v3-real:wer | 640 | 0.110 | [0.086, 0.134] |
| v3-mix-vs-v3-real:wer_gated | 640 | 0.028 | [0.008, 0.047] |
| v3-mix-vs-v2-cal:si_sdri_db | 640 | 2.949 | [2.682, 3.217] |
| v3-mix-vs-v2-cal:der | 640 | -0.157 | [-0.170, -0.145] |
| v3-mix-vs-v2-cal:wer | 640 | -0.102 | [-0.141, -0.065] |
| v3-mix-vs-v2-cal:wer_gated | 640 | -0.166 | [-0.195, -0.138] |
| v3-mix-vs-v1-base:si_sdri_db | 640 | 2.625 | [2.350, 2.903] |
| v3-mix-vs-v1-base:der | 640 | -0.200 | [-0.214, -0.186] |
| v3-mix-vs-v1-base:wer | 640 | -0.085 | [-0.108, -0.064] |
| v3-mix-vs-v1-base:wer_gated | 640 | -0.106 | [-0.126, -0.089] |
