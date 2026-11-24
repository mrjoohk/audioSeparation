# AMI dev: plain vs dominance-gated Whisper WER

Scenes: 160

| System | SI-SDRi (dB) | DER | DOA error (deg) | WER | WER (gated) |
| --- | --- | --- | --- | --- | --- |
| unprocessed | 0.00 | 0.743 | nan | 0.446 | 0.446 |
| base | -0.05 | 0.530 | nan | 0.866 | 0.760 |
| robust | 0.54 | 0.479 | nan | 0.831 | 0.676 |
| cal | 1.41 | 0.440 | nan | 0.794 | 0.682 |

| Paired difference | n | mean | 95 % CI |
| --- | --- | --- | --- |
| cal-vs-unprocessed:si_sdri_db | 160 | 1.406 | [0.801, 2.016] |
| cal-vs-unprocessed:der | 160 | -0.303 | [-0.328, -0.278] |
| cal-vs-unprocessed:wer | 160 | 0.348 | [0.260, 0.454] |
| cal-vs-unprocessed:wer_gated | 160 | 0.236 | [0.195, 0.282] |
| cal-vs-base:si_sdri_db | 160 | 1.461 | [0.901, 2.058] |
| cal-vs-base:der | 160 | -0.090 | [-0.109, -0.070] |
| cal-vs-base:wer | 160 | -0.073 | [-0.166, 0.037] |
| cal-vs-base:wer_gated | 160 | -0.078 | [-0.123, -0.026] |
| cal-vs-robust:si_sdri_db | 160 | 0.865 | [0.392, 1.314] |
| cal-vs-robust:der | 160 | -0.039 | [-0.054, -0.024] |
| cal-vs-robust:wer | 160 | -0.037 | [-0.132, 0.071] |
| cal-vs-robust:wer_gated | 160 | 0.006 | [-0.035, 0.053] |
