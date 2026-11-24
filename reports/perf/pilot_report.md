# Throughput benchmark and F-11 pilot (2026-11-21)

Environment: Python 3.14.8, 12 logical CPUs, workers = 8.

| Requirement | Target | Measured | Result |
| --- | --- | --- | --- |
| REQ-W04 RIR/s (16 kHz, ISM 3), single process | — | 345 | — |
| REQ-W04 RIR/s, 8 workers, steady state | 1000 | 1578 | met |
| same, including process start-up (7.0 s wall) | — | 1139 | — |
| REQ-W10 scenes/h (10 s, 2 src, 4 mic), 8 workers, full storage | 1000 | 13182 | met |
| same, training storage | 1000 | 13513 | met |

## F-11 pilot (16 scenes per profile)

| Profile | QC-passed audio h / h | MB per scene | Fail rate | Storage for 100k audio hours |
| --- | --- | --- | --- | --- |
| full | 47.89 | 16.1 | 0% | 580.1 TB |
| training | 48.75 | 10.0 | 0% | 359.4 TB |

"Audio hours" count rendered scene length (dry duration + reverb tail) per scene.
Storage extrapolation uses the measured bytes per audio second (float32, 4 channels, 2 sources).
