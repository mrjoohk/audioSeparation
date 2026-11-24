# AMI blind2 (frozen candidate v1-cal)

Scenes: 160

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER | WER (gated) |
| --- | --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.756 | nan | 0.540 | 0.540 |
| v1-cal | -0.80 | 0.530 | nan | 0.872 | 0.769 |
| v1-base | 0.20 | 0.535 | nan | 0.865 | 0.758 |
| v2-cal | -0.16 | 0.542 | nan | 0.960 | 0.874 |
| v2-base | -0.58 | 0.563 | nan | 0.865 | 0.803 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| v1-cal-vs-unprocessed:si_sdri_db | 160 | -0.796 | [-1.129, -0.468] |
| v1-cal-vs-unprocessed:der | 160 | -0.226 | [-0.245, -0.210] |
| v1-cal-vs-unprocessed:wer | 160 | 0.332 | [0.299, 0.365] |
| v1-cal-vs-unprocessed:wer_gated | 160 | 0.229 | [0.202, 0.255] |
| v1-cal-vs-v1-base:si_sdri_db | 160 | -0.997 | [-1.451, -0.530] |
| v1-cal-vs-v1-base:der | 160 | -0.006 | [-0.024, 0.013] |
| v1-cal-vs-v1-base:wer | 160 | 0.007 | [-0.032, 0.045] |
| v1-cal-vs-v1-base:wer_gated | 160 | 0.011 | [-0.022, 0.043] |
| v1-cal-vs-v2-cal:si_sdri_db | 160 | -0.633 | [-0.993, -0.286] |
| v1-cal-vs-v2-cal:der | 160 | -0.013 | [-0.029, 0.003] |
| v1-cal-vs-v2-cal:wer | 160 | -0.088 | [-0.206, 0.007] |
| v1-cal-vs-v2-cal:wer_gated | 160 | -0.105 | [-0.205, -0.029] |
| v1-cal-vs-v2-base:si_sdri_db | 160 | -0.221 | [-0.609, 0.182] |
| v1-cal-vs-v2-base:der | 160 | -0.034 | [-0.051, -0.016] |
| v1-cal-vs-v2-base:wer | 160 | 0.007 | [-0.039, 0.046] |
| v1-cal-vs-v2-base:wer_gated | 160 | -0.034 | [-0.077, 0.001] |
