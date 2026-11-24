# AMI dev-b: base with/without feature CORAL (fit on dev-a mixtures)

Scenes: 80

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER |
| --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.736 | nan | nan |
| base | 0.26 | 0.519 | nan | nan |
| base+coral | -0.58 | 0.509 | nan | nan |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| base+coral-vs-base:si_sdri_db | 80 | -0.846 | [-1.528, -0.204] |
| base+coral-vs-base:der | 80 | -0.011 | [-0.033, 0.012] |
| base+coral-vs-unprocessed:si_sdri_db | 80 | -0.582 | [-1.022, -0.089] |
| base+coral-vs-unprocessed:der | 80 | -0.228 | [-0.254, -0.202] |
