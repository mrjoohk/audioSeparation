# LibriSpeech test: plain vs dominance-gated Whisper WER

Scenes: 60

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER | WER (gated) |
| --- | --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.576 | nan | 0.455 | 0.455 |
| base | 0.59 | 0.412 | nan | 0.968 | 0.769 |
| robust | 1.86 | 0.423 | nan | 0.890 | 0.736 |
| cal | 1.91 | 0.400 | nan | 0.895 | 0.765 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| cal-vs-unprocessed:si_sdri_db | 60 | 1.909 | [0.944, 2.934] |
| cal-vs-unprocessed:der | 60 | -0.176 | [-0.236, -0.113] |
| cal-vs-unprocessed:wer | 60 | 0.440 | [0.356, 0.517] |
| cal-vs-unprocessed:wer_gated | 60 | 0.310 | [0.245, 0.376] |
| cal-vs-base:si_sdri_db | 60 | 1.316 | [0.302, 2.347] |
| cal-vs-base:der | 60 | -0.012 | [-0.055, 0.028] |
| cal-vs-base:wer | 60 | -0.073 | [-0.225, 0.055] |
| cal-vs-base:wer_gated | 60 | -0.004 | [-0.095, 0.078] |
| cal-vs-robust:si_sdri_db | 60 | 0.051 | [-0.746, 0.857] |
| cal-vs-robust:der | 60 | -0.022 | [-0.047, 0.003] |
| cal-vs-robust:wer | 60 | 0.005 | [-0.057, 0.065] |
| cal-vs-robust:wer_gated | 60 | 0.029 | [-0.016, 0.076] |
