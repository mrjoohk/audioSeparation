# LibriSpeech test-clean 2-speaker scenes: SI-SDRi, DER, Whisper WER

Scenes: 60

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER |
| --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.576 | nan | 0.602 |
| base | 1.13 | 0.384 | nan | 0.756 |
| robust | 1.39 | 0.419 | nan | 0.936 |
| cal | 0.86 | 0.421 | nan | 0.977 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| robust-vs-unprocessed:si_sdri_db | 60 | 1.385 | [0.474, 2.409] |
| robust-vs-unprocessed:der | 60 | -0.157 | [-0.226, -0.084] |
| robust-vs-unprocessed:wer | 60 | 0.334 | [0.025, 0.605] |
| robust-vs-base:si_sdri_db | 60 | 0.256 | [-0.573, 1.135] |
| robust-vs-base:der | 60 | 0.036 | [0.001, 0.072] |
| robust-vs-base:wer | 60 | 0.180 | [0.046, 0.360] |
| robust-vs-cal:si_sdri_db | 60 | 0.526 | [-0.244, 1.371] |
| robust-vs-cal:der | 60 | -0.002 | [-0.035, 0.031] |
| robust-vs-cal:wer | 60 | -0.040 | [-0.286, 0.215] |
