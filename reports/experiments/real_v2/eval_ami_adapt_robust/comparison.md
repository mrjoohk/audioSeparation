# AMI dev-b: robust with/without feature CORAL (fit on dev-a mixtures)

Scenes: 80

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER |
| --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.736 | nan | nan |
| robust | 0.93 | 0.470 | nan | nan |
| robust+coral | 1.67 | 0.445 | nan | nan |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| robust+coral-vs-robust:si_sdri_db | 80 | 0.735 | [0.080, 1.365] |
| robust+coral-vs-robust:der | 80 | -0.025 | [-0.046, -0.003] |
| robust+coral-vs-unprocessed:si_sdri_db | 80 | 1.669 | [0.850, 2.555] |
| robust+coral-vs-unprocessed:der | 80 | -0.291 | [-0.330, -0.256] |
