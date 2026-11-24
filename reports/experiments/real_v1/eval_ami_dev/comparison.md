# AMI real dev sessions (superposition scenes)

Scenes: 160

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER |
| --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.743 | nan | 0.455 |
| base | 1.18 | 0.500 | nan | 0.946 |
| robust | 1.61 | 0.455 | nan | 0.852 |
| cal | 1.81 | 0.430 | nan | 0.818 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| robust-vs-unprocessed:si_sdri_db | 160 | 1.607 | [1.100, 2.112] |
| robust-vs-unprocessed:der | 160 | -0.288 | [-0.315, -0.264] |
| robust-vs-unprocessed:wer | 160 | 0.397 | [0.334, 0.465] |
| robust-vs-base:si_sdri_db | 160 | 0.426 | [0.028, 0.834] |
| robust-vs-base:der | 160 | -0.045 | [-0.068, -0.023] |
| robust-vs-base:wer | 160 | -0.094 | [-0.225, 0.014] |
| robust-vs-cal:si_sdri_db | 160 | -0.204 | [-0.565, 0.153] |
| robust-vs-cal:der | 160 | 0.025 | [0.009, 0.041] |
| robust-vs-cal:wer | 160 | 0.034 | [-0.038, 0.101] |
