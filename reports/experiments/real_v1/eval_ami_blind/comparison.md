# AMI blind_test (frozen candidate cal)

Scenes: 80

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER |
| --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.753 | nan | 0.511 |
| base | 0.16 | 0.556 | nan | 1.048 |
| cal | -1.84 | 0.512 | nan | 1.068 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| cal-vs-unprocessed:si_sdri_db | 80 | -1.842 | [-2.265, -1.446] |
| cal-vs-unprocessed:der | 80 | -0.242 | [-0.271, -0.214] |
| cal-vs-unprocessed:wer | 80 | 0.557 | [0.409, 0.741] |
| cal-vs-base:si_sdri_db | 80 | -1.999 | [-2.476, -1.529] |
| cal-vs-base:der | 80 | -0.045 | [-0.074, -0.013] |
| cal-vs-base:wer | 80 | 0.020 | [-0.186, 0.228] |
