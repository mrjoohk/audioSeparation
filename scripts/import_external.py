"""
Import downloaded third-party corpora into the W2 asset library.

    .venv/Scripts/python.exe scripts/import_external.py librispeech
    .venv/Scripts/python.exe scripts/import_external.py demand
    .venv/Scripts/python.exe scripts/import_external.py hutubs

Inputs are the archives under data/external/<corpus>/ (downloaded with the
user's approval; not versioned).  The library index is
data/external/library/assets.json.  Archives are extracted with traversal
checks (datagen.external).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datagen.assets import AssetLibrary  # noqa: E402
from datagen.external import (  # noqa: E402
    import_demand,
    import_librispeech,
    safe_extract_tar,
    safe_extract_zip,
)

EXT = ROOT / "data" / "external"
LIB = EXT / "library"


def librispeech(lib: AssetLibrary) -> dict:
    out = {}
    # train-clean-100 (251 speakers, 100 h) is capped at 40 utterances <= 16 s per speaker
    caps = {"train-clean-100": dict(max_s=16.0, max_per_speaker=40)}
    for subset in ("dev-clean", "test-clean", "train-clean-100"):
        d = EXT / "librispeech" / "LibriSpeech" / subset
        tar = EXT / "librispeech" / f"{subset}.tar.gz"
        if not d.exists():
            if not tar.exists():
                continue
            safe_extract_tar(str(tar), str(EXT / "librispeech"))
        out[subset] = len(import_librispeech(str(d), lib, subset, **caps.get(subset, {})))
    return out


def demand(lib: AssetLibrary) -> dict:
    envs = []
    for z in sorted(glob.glob(str(EXT / "demand" / "*_16k.zip"))):
        dest = EXT / "demand" / "extracted"
        env = Path(z).name.split("_")[0]
        if not (dest / env).exists():
            safe_extract_zip(z, str(dest))
        envs.append(str(dest / env))
    ids = import_demand(envs, lib)
    return {"environments": len(envs), "segments": len(ids)}


def hutubs(_lib) -> dict:
    dest = EXT / "hutubs" / "HRIRs"
    if not dest.exists():
        safe_extract_zip(str(EXT / "hutubs" / "HRIRs.zip"), str(dest))
    files = sorted(glob.glob(str(dest / "**" / "*measured*.sofa"), recursive=True))
    with open(EXT / "hutubs" / "subjects.json", "w", encoding="utf-8") as fh:
        json.dump({"license": "CC BY 4.0 (HUTUBS, DOI 10.14279/depositonce-8487)",
                   "measured_sofa": [os.path.relpath(f, ROOT).replace(os.sep, "/") for f in files]}, fh, indent=1)
    return {"measured_subjects": len(files)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", choices=("librispeech", "demand", "hutubs"))
    a = ap.parse_args()
    lib = AssetLibrary(str(LIB))
    res = {"librispeech": librispeech, "demand": demand, "hutubs": hutubs}[a.corpus](lib)
    lib.save()
    print(json.dumps(res))


if __name__ == "__main__":
    main()
