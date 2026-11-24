# LibriSpeech test: plain vs dominance-gated Whisper WER

Scenes: 60

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER | WER (gated) |
| --- | --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.576 | nan | 0.455 | 0.455 |
| base | 1.13 | 0.384 | nan | 0.860 | 0.664 |
| robust | 1.39 | 0.419 | nan | 0.919 | 0.696 |
| cal | 0.86 | 0.421 | nan | 0.927 | 0.767 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| cal-vs-unprocessed:si_sdri_db | 60 | 0.860 | [-0.068, 1.803] |
| cal-vs-unprocessed:der | 60 | -0.155 | [-0.214, -0.097] |
| cal-vs-unprocessed:wer | 60 | 0.472 | [0.362, 0.615] |
| cal-vs-unprocessed:wer_gated | 60 | 0.312 | [0.244, 0.394] |
| cal-vs-base:si_sdri_db | 60 | -0.270 | [-1.171, 0.543] |
| cal-vs-base:der | 60 | 0.037 | [0.010, 0.067] |
| cal-vs-base:wer | 60 | 0.067 | [-0.031, 0.191] |
| cal-vs-base:wer_gated | 60 | 0.103 | [0.042, 0.174] |
| cal-vs-robust:si_sdri_db | 60 | -0.526 | [-1.371, 0.244] |
| cal-vs-robust:der | 60 | 0.002 | [-0.031, 0.035] |
| cal-vs-robust:wer | 60 | 0.008 | [-0.109, 0.140] |
| cal-vs-robust:wer_gated | 60 | 0.071 | [0.002, 0.150] |
