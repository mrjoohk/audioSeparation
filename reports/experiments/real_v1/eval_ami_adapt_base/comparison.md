# AMI dev-b: base with/without feature CORAL (fit on dev-a mixtures)

Scenes: 80

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER |
| --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.736 | nan | nan |
| base | 1.55 | 0.492 | nan | nan |
| base+coral | 0.21 | 0.470 | nan | nan |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| base+coral-vs-base:si_sdri_db | 80 | -1.339 | [-2.001, -0.702] |
| base+coral-vs-base:der | 80 | -0.022 | [-0.051, 0.005] |
| base+coral-vs-unprocessed:si_sdri_db | 80 | 0.210 | [-0.426, 0.888] |
| base+coral-vs-unprocessed:der | 80 | -0.267 | [-0.301, -0.235] |
