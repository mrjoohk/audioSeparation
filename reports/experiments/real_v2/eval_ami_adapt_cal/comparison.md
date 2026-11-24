# AMI dev-b: cal with/without feature CORAL (fit on dev-a mixtures)

Scenes: 80

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER |
| --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.736 | nan | nan |
| cal | 1.27 | 0.457 | nan | nan |
| cal+coral | 1.76 | 0.425 | nan | nan |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| cal+coral-vs-cal:si_sdri_db | 80 | 0.491 | [-0.125, 1.153] |
| cal+coral-vs-cal:der | 80 | -0.033 | [-0.052, -0.013] |
| cal+coral-vs-unprocessed:si_sdri_db | 80 | 1.758 | [0.923, 2.663] |
| cal+coral-vs-unprocessed:der | 80 | -0.312 | [-0.350, -0.277] |
