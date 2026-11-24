# AMI dev-b: robust with/without feature CORAL (fit on dev-a mixtures)

Scenes: 80

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER |
| --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.736 | nan | nan |
| robust | 1.57 | 0.467 | nan | nan |
| robust+coral | 0.86 | 0.459 | nan | nan |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| robust+coral-vs-robust:si_sdri_db | 80 | -0.713 | [-1.387, 0.015] |
| robust+coral-vs-robust:der | 80 | -0.008 | [-0.038, 0.021] |
| robust+coral-vs-unprocessed:si_sdri_db | 80 | 0.860 | [-0.076, 1.873] |
| robust+coral-vs-unprocessed:der | 80 | -0.277 | [-0.317, -0.238] |
