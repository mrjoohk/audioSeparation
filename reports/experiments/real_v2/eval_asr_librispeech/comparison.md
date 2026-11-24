# LibriSpeech test-clean 2-speaker scenes: SI-SDRi, DER, Whisper WER

Scenes: 60

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER |
| --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.576 | nan | 0.602 |
| base | 0.59 | 0.412 | nan | 1.104 |
| robust | 1.86 | 0.423 | nan | 0.869 |
| cal | 1.91 | 0.400 | nan | 0.941 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| robust-vs-unprocessed:si_sdri_db | 60 | 1.858 | [0.981, 2.761] |
| robust-vs-unprocessed:der | 60 | -0.153 | [-0.210, -0.094] |
| robust-vs-unprocessed:wer | 60 | 0.267 | [0.005, 0.465] |
| robust-vs-base:si_sdri_db | 60 | 1.264 | [0.248, 2.272] |
| robust-vs-base:der | 60 | 0.010 | [-0.024, 0.043] |
| robust-vs-base:wer | 60 | -0.235 | [-0.595, 0.038] |
| robust-vs-cal:si_sdri_db | 60 | -0.051 | [-0.857, 0.746] |
| robust-vs-cal:der | 60 | 0.022 | [-0.003, 0.047] |
| robust-vs-cal:wer | 60 | -0.072 | [-0.232, 0.051] |
