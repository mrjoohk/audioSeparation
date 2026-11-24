# AMI real dev sessions (superposition scenes)

Scenes: 160

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER |
| --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.743 | nan | 0.455 |
| base | -0.05 | 0.530 | nan | 0.873 |
| robust | 0.54 | 0.479 | nan | 0.860 |
| cal | 1.41 | 0.440 | nan | 0.856 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| robust-vs-unprocessed:si_sdri_db | 160 | 0.542 | [-0.041, 1.126] |
| robust-vs-unprocessed:der | 160 | -0.264 | [-0.287, -0.243] |
| robust-vs-unprocessed:wer | 160 | 0.405 | [0.326, 0.493] |
| robust-vs-base:si_sdri_db | 160 | 0.597 | [0.129, 1.074] |
| robust-vs-base:der | 160 | -0.051 | [-0.069, -0.034] |
| robust-vs-base:wer | 160 | -0.013 | [-0.093, 0.078] |
| robust-vs-cal:si_sdri_db | 160 | -0.865 | [-1.314, -0.392] |
| robust-vs-cal:der | 160 | 0.039 | [0.024, 0.054] |
| robust-vs-cal:wer | 160 | 0.004 | [-0.123, 0.127] |
