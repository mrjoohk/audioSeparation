# AMI dev-b: cal with/without feature CORAL (fit on dev-a mixtures)

Scenes: 80

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER |
| --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.736 | nan | nan |
| cal | 1.97 | 0.441 | nan | nan |
| cal+coral | 1.18 | 0.429 | nan | nan |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| cal+coral-vs-cal:si_sdri_db | 80 | -0.793 | [-1.513, -0.078] |
| cal+coral-vs-cal:der | 80 | -0.011 | [-0.034, 0.009] |
| cal+coral-vs-unprocessed:si_sdri_db | 80 | 1.176 | [0.183, 2.175] |
| cal+coral-vs-unprocessed:der | 80 | -0.307 | [-0.346, -0.271] |
