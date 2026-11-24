# AMI dev: plain vs dominance-gated Whisper WER

Scenes: 160

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER | WER (gated) |
| --- | --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.743 | nan | 0.446 | 0.446 |
| base | 1.18 | 0.500 | nan | 0.890 | 0.748 |
| robust | 1.61 | 0.455 | nan | 0.834 | 0.672 |
| cal | 1.81 | 0.430 | nan | 0.770 | 0.659 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| cal-vs-unprocessed:si_sdri_db | 160 | 1.812 | [1.230, 2.410] |
| cal-vs-unprocessed:der | 160 | -0.314 | [-0.340, -0.288] |
| cal-vs-unprocessed:wer | 160 | 0.325 | [0.287, 0.365] |
| cal-vs-unprocessed:wer_gated | 160 | 0.214 | [0.186, 0.242] |
| cal-vs-base:si_sdri_db | 160 | 0.631 | [0.151, 1.145] |
| cal-vs-base:der | 160 | -0.070 | [-0.093, -0.047] |
| cal-vs-base:wer | 160 | -0.120 | [-0.183, -0.066] |
| cal-vs-base:wer_gated | 160 | -0.089 | [-0.150, -0.038] |
| cal-vs-robust:si_sdri_db | 160 | 0.204 | [-0.153, 0.565] |
| cal-vs-robust:der | 160 | -0.025 | [-0.041, -0.009] |
| cal-vs-robust:wer | 160 | -0.063 | [-0.103, -0.023] |
| cal-vs-robust:wer_gated | 160 | -0.013 | [-0.044, 0.020] |
