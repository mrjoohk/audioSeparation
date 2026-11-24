# NOTSOFAR dev1: v4 selection (design §19)

Scenes: 473

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER | WER (gated) |
| --- | --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.891 | nan | 0.378 | 0.378 |
| v2-base | -0.69 | 0.620 | nan | 0.847 | 0.752 |
| v4-nsf | 1.09 | 0.588 | nan | 0.744 | 0.591 |
| v4-real | 4.38 | 0.320 | nan | 0.618 | 0.505 |
| v3-real | 0.93 | 0.429 | nan | 0.640 | 0.517 |
| v3-mix | 1.26 | 0.545 | nan | 0.856 | 0.725 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| v4-nsf-vs-unprocessed:si_sdri_db | 473 | 1.089 | [0.840, 1.326] |
| v4-nsf-vs-unprocessed:der | 473 | -0.303 | [-0.317, -0.291] |
| v4-nsf-vs-unprocessed:wer | 473 | 0.366 | [0.343, 0.389] |
| v4-nsf-vs-unprocessed:wer_gated | 473 | 0.213 | [0.196, 0.230] |
| v4-nsf-vs-unprocessed:cpwer | 473 | -0.063 | [-0.081, -0.044] |
| v4-nsf-vs-unprocessed:cpwer_gated | 473 | -0.102 | [-0.113, -0.090] |
| v4-nsf-vs-v2-base:si_sdri_db | 473 | 1.784 | [1.523, 2.049] |
| v4-nsf-vs-v2-base:der | 473 | -0.032 | [-0.044, -0.021] |
| v4-nsf-vs-v2-base:wer | 473 | -0.102 | [-0.127, -0.077] |
| v4-nsf-vs-v2-base:wer_gated | 473 | -0.161 | [-0.183, -0.138] |
| v4-nsf-vs-v2-base:cpwer | 473 | -0.064 | [-0.087, -0.040] |
| v4-nsf-vs-v2-base:cpwer_gated | 473 | -0.053 | [-0.075, -0.033] |
| v4-nsf-vs-v4-real:si_sdri_db | 473 | -3.288 | [-3.677, -2.894] |
| v4-nsf-vs-v4-real:der | 473 | 0.267 | [0.252, 0.282] |
| v4-nsf-vs-v4-real:wer | 473 | 0.127 | [0.093, 0.160] |
| v4-nsf-vs-v4-real:wer_gated | 473 | 0.087 | [0.057, 0.112] |
| v4-nsf-vs-v4-real:cpwer | 473 | 0.177 | [0.142, 0.210] |
| v4-nsf-vs-v4-real:cpwer_gated | 473 | 0.201 | [0.171, 0.227] |
| v4-nsf-vs-v3-real:si_sdri_db | 473 | 0.157 | [-0.204, 0.502] |
| v4-nsf-vs-v3-real:der | 473 | 0.158 | [0.143, 0.173] |
| v4-nsf-vs-v3-real:wer | 473 | 0.104 | [0.079, 0.130] |
| v4-nsf-vs-v3-real:wer_gated | 473 | 0.074 | [0.054, 0.093] |
| v4-nsf-vs-v3-real:cpwer | 473 | 0.085 | [0.061, 0.111] |
| v4-nsf-vs-v3-real:cpwer_gated | 473 | 0.098 | [0.077, 0.119] |
| v4-nsf-vs-v3-mix:si_sdri_db | 473 | -0.169 | [-0.513, 0.179] |
| v4-nsf-vs-v3-mix:der | 473 | 0.042 | [0.028, 0.057] |
| v4-nsf-vs-v3-mix:wer | 473 | -0.112 | [-0.137, -0.086] |
| v4-nsf-vs-v3-mix:wer_gated | 473 | -0.133 | [-0.157, -0.111] |
| v4-nsf-vs-v3-mix:cpwer | 473 | -0.040 | [-0.063, -0.015] |
| v4-nsf-vs-v3-mix:cpwer_gated | 473 | 0.020 | [-0.002, 0.041] |
