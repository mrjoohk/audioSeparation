"""
Experiments on real third-party data (stages 3-7 blocked items).

Data (downloaded with the user's approval, data/external/, not versioned):
  LibriSpeech dev-clean / test-clean (CC BY 4.0) - real read speech + transcripts
  DEMAND 16 kHz (CC BY-SA 3.0)                   - real environment noise
  AMI meetings, Array1 + headsets (CC BY 4.0)    - real rooms / device / speech
  Whisper small.en (MIT)                         - real ASR

Speech split is the corpus's own speaker-disjoint split: dev-clean speakers
train, test-clean speakers test.  Rooms and DEMAND environments are split
with datagen.planner.split_pools (no shared keys).

Stages (outputs under reports/experiments/real_<tag>/, scenes under
data/external/work/).  --tag v1 trains on dev-clean (40 speakers); --tag v2
on train-clean-100 + dev-clean (291 speakers), test sets unchanged:
  train_base   baseline: ONE synthetic room ("room A"), circular4, no augmentation
  train_robust robust: domain-randomised rooms (RT60 0.15-1.2 s, half band
               reverb), circular4/pair10/circular4_r10, DEMAND noise (p=0.5,
               5-25 dB SNR) and device augmentation
  train_cal    as robust, but RT60 targets = blind-RT60 profile of the AMI dev
               sessions (REQ-302 calibration fed by real recordings)
  asr          LibriSpeech test-clean 2-speaker scenes (utterances 3-8 s fully
               inside 12 s scenes): SI-SDRi, DER and Whisper WER for
               unprocessed / baseline / robust
  heldout      synthetic held-out arrays (circular3_r3, linear3_4cm,
               square4_8cm) + matched circular4 control, test-clean speakers
  ami_build    AMI session registry (configs/real_sessions_ami.csv), session
               splits dev / blind_test (room+speaker groups), blind-RT60
               calibration profile from dev sessions, and real-room 2-speaker
               superposition scenes (datatools.ami)
  ami_eval     real dev comparison (SI-SDRi, DER, Whisper WER) of all systems;
               the candidate with the best dev SI-SDRi is frozen and only then
               evaluated on blind_test (datatools.real_sessions.BlindTestGuard)

Every neural system uses the same fixed AGC front end (input RMS = median
reference-channel RMS of the training scenes), because AMI recordings are
~20 dB quieter than the synthetic training data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datagen.assets import AssetLibrary  # noqa: E402
from datagen.planner import ScenarioPrior, make_room_catalog, sample_scenarios, split_pools  # noqa: E402
from datagen.publish import generate_dataset  # noqa: E402
from training.augment import AugmentConfig  # noqa: E402

EXT = ROOT / "data" / "external"
WORK = EXT / "work"
OUT_V1 = ROOT / "reports" / "experiments" / "real_v1"
OUT = OUT_V1
# --tag v2: same recipes, larger training corpus (train-clean-100 + dev-clean, 291 speakers)
TAGS = {"v1": {"train_subsets": ("dev-clean",), "sfx": ""},
        "v2": {"train_subsets": ("train-clean-100", "dev-clean"), "sfx": "_v2"},
        # v3 (design §16): v2 synthetic corpus + real AMI ES/IS training meetings (train_v3)
        "v3": {"train_subsets": ("train-clean-100", "dev-clean"), "sfx": "_v3"}}
TAG = TAGS["v1"]
HELD_OUT = ("circular3_r3", "linear3_4cm", "square4_8cm")
FS = 16000


def library():
    lib = AssetLibrary(str(EXT / "library"))
    if not lib.assets:
        raise SystemExit("run scripts/import_external.py librispeech (and demand) first")
    return lib


def base_prior(**kw) -> ScenarioPrior:
    d = dict(arrays=("circular4",), duration_s=4.0, ism_order=2, n_speakers=(2, 2),
             tiers={"medium": 0.2, "hard": 0.5}, tier_weights={"medium": 1, "hard": 1},
             noise_prob=0.0, event_prob=0.0, storage_profile="training", n_room_templates=60,
             materials=("wood", "brick", "carpet", "acoustic_tile", "concrete"))
    d.update(kw)
    return ScenarioPrior(**d)


def world(lib, seed=0):
    prior = base_prior()
    rooms = make_room_catalog(prior, seed=seed)
    pools = split_pools(lib, rooms, {"train": 0.8, "test": 0.2}, seed=seed)
    for split, subsets in (("train", TAG["train_subsets"]), ("test", ("test-clean",))):
        pools[split]["speech"] = sorted(a.asset_id for a in lib.of_kind("speech")
                                        if a.meta.get("subset") in subsets)
    return rooms, pools


def scenes_of(plans, d):
    out = []
    for p in plans:
        m = os.path.join(d, p["config"]["scene_id"], "scene_manifest.json")
        if os.path.exists(m):
            out.append((m, None))
    return out


def gen(lib, prior, rooms, pools, split, n, seed, name, workers, mutate=None):
    d = str(WORK / name)
    plans = sample_scenarios(prior, n, lib, pools, rooms, split, seed=seed, output_dir=d)
    for p in plans:
        if mutate:
            mutate(p)
    done = WORK / name / "_done.json"
    if not done.exists():
        generate_dataset(plans, d, workers=workers)
        done.write_text(json.dumps({"n": n, "seed": seed}))
    return scenes_of(plans, d), plans


def dr_targets():
    return [round(float(v), 3) for v in np.linspace(0.15, 1.2, 22)]


def robust_prior(rt60_samples, noise=True):
    kw = dict(arrays=("circular4", "pair10", "circular4_r10"),
              calibration={"id": "rt60", "rt60_samples": rt60_samples})
    if noise:
        kw.update(noise_prob=0.5, snr_db=(5.0, 25.0))
    return base_prior(**kw)


def half_band_reverb(seed):
    rng = np.random.default_rng(seed)

    def f(p):
        p["config"]["render"]["band_reverb"] = bool(rng.random() < 0.5)
    return f


def stage_train(kind, a):
    from training.neural import train_net
    lib = library()
    rooms, pools = world(lib, a.seed)
    if kind == "base":
        room_a = pools["train"]["rooms"][0]
        pools_a = {"train": {**pools["train"], "rooms": [room_a]}}
        tr, _ = gen(lib, base_prior(materials=("wood",)), rooms, pools_a, "train", a.n_train,
                    a.seed + 1, "train_base" + TAG["sfx"], a.workers)
        aug = None
    else:
        if kind == "robust":
            targets = dr_targets()
        else:
            prof = json.loads((OUT_V1 / "ami_calibration_profile.json").read_text(encoding="utf-8"))
            targets = prof["rt60_samples"]
        tr, _ = gen(lib, robust_prior(targets), rooms, pools, "train", a.n_train, a.seed + 2,
                    f"train_{kind}" + TAG["sfx"], a.workers, half_band_reverb(a.seed + 77))
        aug = AugmentConfig()
    if a.generate_only:
        print(json.dumps({"stage": f"generate_{kind}", "n_scenes": len(tr)}))
        return
    exp = train_net(tr, str(OUT / f"model_{kind}"), steps=a.steps, batch=a.batch, seed=a.seed, augment=aug,
                    device=a.device, loader_threads=a.loader_threads,
                    data_identity={"corpus": "LibriSpeech " + " + ".join(TAG["train_subsets"]) + " (CC BY 4.0)",
                                   "stage": kind})
    print(json.dumps({"stage": f"train_{kind}", "n_scenes": len(tr), "train_time_s": exp["metrics"]["train_time_s"],
                      "final_si_sdr_db": exp["metrics"]["train_log"][-1]["si_sdr_db"]}))


def agc_target() -> float:
    f = OUT / "agc.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))["input_rms_dbfs"]
    from datatools.loader import load_scene
    ms = sorted((WORK / ("train_base" + TAG["sfx"])).glob("*/scene_manifest.json"))[:100]
    vals = []
    for m in ms:
        b = load_scene(str(m))
        x = b.mixture[b.reference_channel].astype(np.float64)
        vals.append(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12))
    t = float(np.median(vals))
    f.write_text(json.dumps({"input_rms_dbfs": t, "n_scenes": len(vals),
                             "source": "median reference-channel RMS of train_base scenes"}), encoding="utf-8")
    return t


def systems(names):
    from training.neural import NeuralSeparator, load_net
    from training.systems import Unprocessed
    out = []
    agc = agc_target()
    for n in names:
        if n == "unprocessed":
            out.append(Unprocessed())
        else:
            out.append(NeuralSeparator(load_net(str(OUT / f"model_{n}" / "masknet.pt")), name=n,
                                       input_rms_dbfs=agc))
    return out


def available_models():
    return [k for k in ("base", "robust", "cal") if (OUT / f"model_{k}" / "masknet.pt").exists()]


def librispeech_asr_set(a):
    """LibriSpeech test-clean 2-speaker scenes whose utterances are all complete, with transcripts."""
    lib = library()
    rooms, pools = world(lib, a.seed)
    short = [i for i in pools["test"]["speech"] if 3.0 <= lib.assets[i].n_samples / FS <= 8.0]
    pools_t = {"test": {**pools["test"], "speech": short}}
    prior = base_prior(duration_s=12.0, max_duration_s=12.0, calibration={"id": "rt60-grid",
                       "rt60_samples": [0.2, 0.3, 0.4, 0.5, 0.6]})
    sc, plans = gen(lib, prior, rooms, pools_t, "test", a.n_test, a.seed + 3, "test_asr", a.workers)
    transcripts = {}
    by_id = {p["config"]["scene_id"]: p for p in plans}
    for m, _ in sc:
        man = json.loads(Path(m).read_text(encoding="utf-8"))
        p = by_id[man["scene_id"]]
        T = man["render"]["n_samples"] / FS
        utts = sorted(zip([s["onset_s"] for s in p["config"]["sources"] if s["role"] == "speech"], p["plan"]["utterances"]))
        if all(o + lib.assets[u].n_samples / FS <= T for o, u in utts):     # every utterance complete
            transcripts[m] = " ".join(lib.assets[u].meta["transcript"] for _, u in utts)
    return [s for s in sc if s[0] in transcripts], transcripts


def stage_asr(a):
    from evaluation.asr import WhisperAsrBackend
    from evaluation.compare import evaluate_systems
    sc, transcripts = librispeech_asr_set(a)
    asr = WhisperAsrBackend("small.en", download_root=str(EXT / "whisper"))
    names = ["unprocessed"] + available_models()
    cand = "robust" if "robust" in names else names[-1]
    rep = evaluate_systems(sc, systems(names), cand, [n for n in names if n != cand],
                           out_dir=str(OUT / "eval_asr_librispeech"), asr=asr, transcripts=transcripts,
                           title="LibriSpeech test-clean 2-speaker scenes: SI-SDRi, DER, Whisper WER",
                           meta={"asr": asr.name, "n_scenes": len(sc)})
    print(json.dumps(rep["summary"]["means"]))


def stage_asr_gate(a):
    """REQ-305/402: word-level Whisper with dominance gating (evaluation.asr.gate_segments).

    One transcription pass per stream gives both the plain WER (as before) and the
    gated WER, where a word is kept only inside its stream's diarized active
    intervals.  Rule and padding (0.1 s) fixed before this run.  Sets: AMI dev and
    LibriSpeech test.  blind_test is never opened here.
    """
    from datatools.real_sessions import BlindTestGuard, load_registry
    from evaluation.asr import WhisperAsrBackend
    from evaluation.compare import evaluate_systems
    asr = WhisperAsrBackend("small.en", download_root=str(EXT / "whisper"), word_level=True)
    models = available_models()
    names = ["unprocessed"] + models
    cand = "cal" if "cal" in models else models[-1]
    refs = [n for n in names if n != cand]
    index = json.loads((WORK / "ami_index.json").read_text(encoding="utf-8"))
    dev_sessions = set(BlindTestGuard(load_registry(str(REGISTRY))).open("dev"))
    dev = [r for r in index["dev"] if f"ami-{r['meeting']}" in dev_sessions]
    out = {"asr": asr.name, "gate": "word midpoint inside own stream's diarized interval +/- 0.1 s"}
    rep = evaluate_systems([(r["manifest"], None) for r in dev], systems(names), cand, refs,
                           out_dir=str(OUT / "eval_ami_dev_gated"), asr=asr,
                           transcripts={r["manifest"]: r["transcript"] for r in dev},
                           title="AMI dev: plain vs dominance-gated Whisper WER", meta={"asr": asr.name})
    out["ami_dev"] = rep["summary"]["means"]
    sc, transcripts = librispeech_asr_set(a)
    rep = evaluate_systems(sc, systems(names), cand, refs, out_dir=str(OUT / "eval_asr_librispeech_gated"),
                           asr=asr, transcripts=transcripts,
                           title="LibriSpeech test: plain vs dominance-gated Whisper WER", meta={"asr": asr.name})
    out["librispeech_test"] = rep["summary"]["means"]
    (OUT / "asr_gate.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out))


def stage_heldout(a):
    from evaluation.compare import evaluate_systems
    lib = library()
    rooms, pools = world(lib, a.seed)
    res = {}
    names = available_models()
    for i, arr in enumerate(("circular4",) + HELD_OUT):
        sc, _ = gen(lib, base_prior(arrays=(arr,)), rooms, pools, "test", a.n_test, a.seed + 10 + i,
                    f"test_arr_{arr}", a.workers)
        rep = evaluate_systems(sc, systems(names), names[-1], names[:-1],
                               out_dir=str(OUT / f"eval_array_{arr}"), title=f"held-out array {arr}")
        res[arr] = {k: v["si_sdri_db"] for k, v in rep["summary"]["means"].items()}
    (OUT / "heldout_arrays.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res))


AMI_MEETINGS = ("ES2002a", "ES2002b", "IS1009a", "IS1009b", "TS3003a", "TS3003b")
AMI_ZIP = EXT / "ami" / "ami_public_manual_1.6.2.zip"
REGISTRY = ROOT / "configs" / "real_sessions_ami.csv"


def stage_ami_build(a):
    from datatools.ami import blind_rt60_of_meeting, build_meeting_scenes, parse_meeting, registry_row, \
        single_speaker_windows
    from datatools.real_sessions import assign_session_splits, label_availability, validate_rows, write_registry
    from training.calibration import fit_profile
    meetings = [m for m in AMI_MEETINGS if len(list((EXT / "ami" / m).glob(f"{m}.Array1-0*.wav"))) == 8]
    rows = validate_rows([{k: (";".join(v) if isinstance(v, list) else str(v).lower() if isinstance(v, bool) else v)
                           for k, v in registry_row(m, parse_meeting(str(AMI_ZIP), m)).items()} for m in meetings])
    rows = assign_session_splits(rows, {"dev": 0.5, "blind_test": 0.5}, seed=a.seed)
    write_registry(rows, str(REGISTRY))
    split = {r["session_id"][4:]: r["split"] for r in rows}
    rng = np.random.default_rng(a.seed)
    rt60 = {}
    index = {"dev": [], "blind_test": []}
    for m in meetings:
        sp = split[m]
        if sp == "dev":
            wins = single_speaker_windows(parse_meeting(str(AMI_ZIP), m))
            for k, v in enumerate(blind_rt60_of_meeting(str(EXT / "ami" / m), m, wins)):
                rt60[f"{m}-{k}"] = v
        index[sp] += build_meeting_scenes(str(AMI_ZIP), str(EXT / "ami" / m), m, str(WORK / f"ami_{sp}"),
                                          a.n_ami, rng)
    prof = fit_profile(rt60, data_version="ami-dev:" + ",".join(m for m in meetings if split[m] == "dev"))
    (OUT / "ami_calibration_profile.json").write_text(json.dumps(prof, indent=1), encoding="utf-8")
    (WORK / "ami_index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    summary = {"meetings": meetings, "splits": split, "n_scenes": {k: len(v) for k, v in index.items()},
               "rt60_dev_median_s": prof["rt60_median_s"], "n_rt60": len(rt60),
               "label_availability_dev": label_availability(rows, "dev")}
    (OUT / "ami_build.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary))


def stage_ami_eval(a):
    import hashlib
    from datatools.real_sessions import BlindTestGuard, load_registry
    from evaluation.asr import WhisperAsrBackend
    from evaluation.compare import evaluate_systems
    index = json.loads((WORK / "ami_index.json").read_text(encoding="utf-8"))
    guard = BlindTestGuard(load_registry(str(REGISTRY)))
    asr = WhisperAsrBackend("small.en", download_root=str(EXT / "whisper"))
    models = available_models()
    dev_sessions = set(guard.open("dev"))
    dev = [r for r in index["dev"] if f"ami-{r['meeting']}" in dev_sessions]
    names = ["unprocessed"] + models
    cand = "robust" if "robust" in models else models[-1]
    rep = evaluate_systems([(r["manifest"], None) for r in dev], systems(names), cand,
                           [n for n in names if n != cand], out_dir=str(OUT / "eval_ami_dev"), asr=asr,
                           transcripts={r["manifest"]: r["transcript"] for r in dev},
                           title="AMI real dev sessions (superposition scenes)", meta={"asr": asr.name})
    means = rep["summary"]["means"]
    best = max(models, key=lambda m: means[m]["si_sdri_db"])
    if TAG is not TAGS["v1"]:
        out = {"dev_means": means, "dev_paired": rep["summary"]["paired"], "dev_best": best,
               "blind_test": "not reopened: the v1 candidate already used these sessions once"}
        (OUT / "ami_eval.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(json.dumps(out))
        return
    ck = OUT / f"model_{best}" / "masknet.pt"
    sha = hashlib.sha256(ck.read_bytes()).hexdigest()
    guard.freeze(sha)
    blind_sessions = set(guard.open("blind_test", sha))
    blind = [r for r in index["blind_test"] if f"ami-{r['meeting']}" in blind_sessions]
    bnames = ["unprocessed"] + (["base"] if best != "base" and "base" in models else []) + [best]
    rep_b = evaluate_systems([(r["manifest"], None) for r in blind], systems(bnames), best,
                             [n for n in bnames if n != best], out_dir=str(OUT / "eval_ami_blind"), asr=asr,
                             transcripts={r["manifest"]: r["transcript"] for r in blind},
                             title=f"AMI blind_test (frozen candidate {best})", meta={"frozen_sha256": sha})
    out = {"dev_means": means, "dev_paired": rep["summary"]["paired"], "frozen_candidate": best,
           "frozen_sha256": sha, "blind_means": rep_b["summary"]["means"], "blind_paired": rep_b["summary"]["paired"],
           "blind_access_log": guard.access_log}
    (OUT / "ami_eval.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out))


def stage_ami_adapt(a):
    """REQ-304 on real data: feature-level CORAL fitted on unlabeled AMI dev mixtures.

    Rule fixed before the run: target statistics come from the dev sessions ending in
    'a' (mixtures only); evaluation is on the dev sessions ending in 'b'.  CORAL is
    adopted for a model only if the paired SI-SDRi gain over the same model without
    adaptation has a 95 % CI above 0.  blind_test is not opened (it was used once by
    ami_eval).
    """
    from datatools.loader import load_scene
    from datatools.real_sessions import BlindTestGuard, load_registry
    from evaluation.compare import evaluate_systems
    from training.neural import NeuralSeparator, fit_feature_coral, load_net
    index = json.loads((WORK / "ami_index.json").read_text(encoding="utf-8"))
    dev_sessions = set(BlindTestGuard(load_registry(str(REGISTRY))).open("dev"))
    dev = [r for r in index["dev"] if f"ami-{r['meeting']}" in dev_sessions]
    fit_rows = [r for r in dev if r["meeting"].endswith("a")]
    eval_rows = [r for r in dev if r["meeting"].endswith("b")]
    target = [load_scene(r["manifest"]) for r in fit_rows]
    agc = agc_target()
    res = {"fit_meetings": sorted({r["meeting"] for r in fit_rows}),
           "eval_meetings": sorted({r["meeting"] for r in eval_rows}),
           "n_fit": len(fit_rows), "n_eval": len(eval_rows), "models": {}}
    from training.systems import Unprocessed
    for m in available_models():
        net = load_net(str(OUT / f"model_{m}" / "masknet.pt"))
        plain = NeuralSeparator(net, name=m, input_rms_dbfs=agc)
        src_dirs = sorted((WORK / f"train_{m}{TAG['sfx']}").glob("*/scene_manifest.json"))[:100]
        source = [load_scene(str(s)) for s in src_dirs]
        ad = fit_feature_coral(plain, source, target)
        adapted = NeuralSeparator(net, name=f"{m}+coral", input_rms_dbfs=agc, adapter=ad)
        rep = evaluate_systems([(r["manifest"], None) for r in eval_rows], [Unprocessed(), plain, adapted],
                               adapted.name, [m, "unprocessed"], out_dir=str(OUT / f"eval_ami_adapt_{m}"),
                               title=f"AMI dev-b: {m} with/without feature CORAL (fit on dev-a mixtures)")
        pr = rep["summary"]["paired"][f"{m}+coral-vs-{m}:si_sdri_db"]
        res["models"][m] = {"means": rep["summary"]["means"], "coral_vs_plain_si_sdri": pr,
                            "adopted": bool(pr["ci95"][0] > 0)}
    (OUT / "ami_adapt.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res))


def _exit_without_teardown(code: int) -> None:
    """Flush and end the process without running DLL unload handlers (Windows)."""
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k32.TerminateProcess(k32.GetCurrentProcess(), code)
    os._exit(code)


# ---- second blind test (design §15 "blind2 판정 규약", fixed before any blind2 data was processed)
# TNO meetings only: room-disjoint from dev (Edinburgh, IDIAP) and speaker-disjoint from every
# meeting used before.  TS3003 (opened once by the v1 candidate) is retired.  Every listed
# meeting that is on disk is included; scenes use a per-meeting seed so adding meetings never
# changes the scenes of the others.
BLIND2_MEETINGS = tuple(f"{s}{v}" for s in ("TS3007", "TS3004", "TS3005", "TS3006", "TS3008") for v in "abcd")
REGISTRY2 = ROOT / "configs" / "real_sessions_ami_blind2.csv"
BLIND2_OUT = ROOT / "reports" / "experiments" / "ami_blind2"
BLIND2_SEED = 100
REQ303_GAIN_DB = 1.5
REQ305_PP = -3.0
REQ402_WER_REL = -0.15
REQ402_DER_PP = -5.0
MIN_SESSIONS = 20


def blind2_meetings():
    return [m for m in BLIND2_MEETINGS if len(list((EXT / "ami" / m).glob(f"{m}.Array1-0*.wav"))) == 8]


def blind2_registry(meetings, path=None):
    """dev rows from the first registry + new blind rows; raises LeakageError on room/speaker overlap."""
    from datatools.ami import parse_meeting, registry_row
    from datatools.real_sessions import assign_session_splits, load_registry, validate_rows, write_registry
    dev = [r for r in load_registry(str(REGISTRY)) if r["split"] == "dev"]
    new = []
    for m in meetings:
        r = registry_row(m, parse_meeting(str(AMI_ZIP), m))
        r["split"] = "blind_test"
        new.append({k: (";".join(v) if isinstance(v, list) else str(v).lower() if isinstance(v, bool) else v)
                    for k, v in r.items()})
    rows = assign_session_splits(dev + validate_rows(new), {"dev": 0.5, "blind_test": 0.5})
    write_registry(rows, str(path or REGISTRY2))
    return rows


def stage_ami_blind2_build(a):
    from datatools.ami import build_meeting_scenes
    meetings = blind2_meetings()
    if not meetings:
        raise SystemExit("no blind2 meetings on disk")
    rows = blind2_registry(meetings)
    idx_path = WORK / "ami_blind2_index.json"
    index = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    for m in meetings:
        if m in index:
            continue
        rng = np.random.default_rng([BLIND2_SEED, int(m[2:6]), ord(m[-1])])
        index[m] = build_meeting_scenes(str(AMI_ZIP), str(EXT / "ami" / m), m, str(WORK / "ami_blind2"), a.n_ami, rng)
        idx_path.write_text(json.dumps(index, indent=1), encoding="utf-8")
    BLIND2_OUT.mkdir(parents=True, exist_ok=True)
    summary = {"meetings": meetings, "n_sessions": len(meetings),
               "n_scenes": {m: len(index[m]) for m in meetings},
               "registry": str(REGISTRY2.relative_to(ROOT)).replace(os.sep, "/"),
               "splits": {r["session_id"]: r["split"] for r in rows}}
    (BLIND2_OUT / "build.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary))


def blind2_candidate():
    """Pre-registered: highest saved AMI dev SI-SDRi over every trained model (v1, v2)."""
    best = None
    for tag in ("v1", "v2"):                                 # the models that existed when blind2 was registered
        f = ROOT / "reports" / "experiments" / f"real_{tag}" / "ami_eval.json"
        if not f.exists():
            continue
        for m, v in json.loads(f.read_text(encoding="utf-8"))["dev_means"].items():
            ck = ROOT / "reports" / "experiments" / f"real_{tag}" / f"model_{m}" / "masknet.pt"
            if m != "unprocessed" and ck.exists() and (best is None or v["si_sdri_db"] > best[2]):
                best = (tag, m, v["si_sdri_db"])
    return best


def session_paired(rows, cand, ref, metric):
    """Per-session mean difference (cand - ref) with a bootstrap over sessions (design §6.2)."""
    from evaluation.compare import paired_bootstrap
    by = {}
    for r in rows:
        by.setdefault((r["scene_id"], r["system"]), r)
    per = {}
    for (sid, s), r in by.items():
        if s == cand and (sid, ref) in by and metric in r and metric in by[(sid, ref)]:
            per.setdefault(sid.rsplit("_", 1)[0], []).append(r[metric] - by[(sid, ref)][metric])
    diffs = [float(np.mean(v)) for v in per.values()]
    m, lo, hi = paired_bootstrap(diffs)
    return {"n_sessions": len(diffs), "mean_diff": m, "ci95": [lo, hi]}


def stage_ami_blind2_eval(a):
    import hashlib
    from datatools.real_sessions import BlindTestGuard, load_registry
    from evaluation.asr import WhisperAsrBackend
    from evaluation.compare import evaluate_systems
    from training.neural import NeuralSeparator, load_net
    from training.systems import Unprocessed
    index = json.loads((WORK / "ami_blind2_index.json").read_text(encoding="utf-8"))
    tag, model, dev_db = blind2_candidate()
    exp = ROOT / "reports" / "experiments"
    sha = hashlib.sha256((exp / f"real_{tag}" / f"model_{model}" / "masknet.pt").read_bytes()).hexdigest()
    guard = BlindTestGuard(load_registry(str(REGISTRY2)))
    guard.freeze(sha)
    sessions = guard.open("blind_test", sha)
    log_path = BLIND2_OUT / "access_log.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    if log:
        if log[-1]["frozen_sha256"] != sha:
            raise PermissionError("blind2 was opened for a different candidate; it is not reopened")
        if set(sessions) <= set(log[-1]["sessions"]):
            raise PermissionError("blind2 already evaluated on these sessions; it is not reopened")
    log.append({"frozen_sha256": sha, "candidate": f"{tag}-{model}", "sessions": sessions})
    BLIND2_OUT.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=1), encoding="utf-8")
    cand, base = f"{tag}-{model}", f"{tag}-base"
    names = ["unprocessed", cand, base]
    other = [t for t in TAGS if t != tag]
    for t in other:                                          # reported, not judged
        names += [f"{t}-{m}" for m in ("cal", "base") if (exp / f"real_{t}" / f"model_{m}" / "masknet.pt").exists()]
    syss = [Unprocessed()]
    for n in names[1:]:
        t, m = n.split("-", 1)
        agc = json.loads((exp / f"real_{t}" / "agc.json").read_text(encoding="utf-8"))["input_rms_dbfs"]
        syss.append(NeuralSeparator(load_net(str(exp / f"real_{t}" / f"model_{m}" / "masknet.pt")), name=n,
                                    input_rms_dbfs=agc))
    recs = [r for m, rs in index.items() if f"ami-{m}" in sessions for r in rs]
    asr = WhisperAsrBackend("small.en", download_root=str(EXT / "whisper"), word_level=True)
    rep = evaluate_systems([(r["manifest"], None) for r in recs], syss, cand, [n for n in names if n != cand],
                           out_dir=str(BLIND2_OUT / "eval"), asr=asr,
                           transcripts={r["manifest"]: r["transcript"] for r in recs},
                           title=f"AMI blind2 (frozen candidate {cand})", meta={"frozen_sha256": sha, "asr": asr.name})
    rows, means = rep["rows"], rep["summary"]["means"]
    n_sess = len(sessions)
    sdr = session_paired(rows, cand, base, "si_sdri_db")
    w = session_paired(rows, cand, base, "wer")
    wg = session_paired(rows, cand, base, "wer_gated")
    u_wer, c_wer = means["unprocessed"]["wer"], means[cand]["wer"]
    wer_rel = (c_wer - u_wer) / u_wer if u_wer > 0 else float("nan")
    der_pp = 100 * (means[cand]["der"] - means["unprocessed"]["der"])
    verdict = {
        "REQ-303": {"rule": f"cand - base SI-SDRi >= +{REQ303_GAIN_DB} dB", **sdr,
                    "met": sdr["mean_diff"] >= REQ303_GAIN_DB},
        "REQ-305": {"rule": f"cand - base WER <= {REQ305_PP} pp, session CI upper < 0, >= {MIN_SESSIONS} sessions",
                    "mean_diff_pp": 100 * w["mean_diff"], "ci95_pp": [100 * x for x in w["ci95"]],
                    "n_sessions": n_sess,
                    "met": (n_sess >= MIN_SESSIONS and 100 * w["mean_diff"] <= REQ305_PP and w["ci95"][1] < 0)
                    if n_sess >= MIN_SESSIONS else None,
                    "withheld": n_sess < MIN_SESSIONS,
                    "gated_secondary_pp": {"mean": 100 * wg["mean_diff"], "ci95": [100 * x for x in wg["ci95"]]}},
        "REQ-402": {"rule": "WER relative <= -15 % and DER <= -5.0 pp vs unprocessed",
                    "wer_rel": wer_rel, "der_pp": der_pp,
                    "met": wer_rel <= REQ402_WER_REL and der_pp <= REQ402_DER_PP},
    }
    out = {"candidate": cand, "candidate_dev_si_sdri_db": dev_db, "baseline": base, "frozen_sha256": sha,
           "n_sessions": n_sess, "sessions": sessions, "n_scenes": len(recs), "means": means, "verdict": verdict}
    (BLIND2_OUT / "result.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out))


# ---------------------------------------------------------------------------
# v3: real AMI training data + blind3 (design §16, fixed before training and before
# any blind3 processing; machine-readable copy reports/experiments/ami_blind3/preregistration.json)
# ---------------------------------------------------------------------------
AMI_TRAIN = tuple([f"ES2004{x}" for x in "abcd"] + [f"ES2014{x}" for x in "abcd"] + ["IS1003a", "IS1003c", "IS1003d"]
                  + [f"IS1006{x}" for x in "abcd"] + ["IS1007a"])
AMI_TRAIN_SEED = 300
AMI_TRAIN_PER_MEETING = 80
AMI_TRAIN_CHANNELS = (0, 1, 7)          # Array1 mic 1 (reference) and its two nearest neighbours
BLIND3_MEETINGS = tuple(f"TS30{n:02d}{x}" for n in range(9, 13) for x in "abcd")
REGISTRY3 = ROOT / "configs" / "real_sessions_ami_blind3.csv"
BLIND3_OUT = ROOT / "reports" / "experiments" / "ami_blind3"
V3_MODELS = ("mix", "real")
V3_BASELINE = ("v2", "base")
EXP = ROOT / "reports" / "experiments"


def _speakers(meetings):
    from datatools.ami import parse_meeting
    return {s.global_id for m in meetings for s in parse_meeting(str(AMI_ZIP), m).values()}


def check_train_disjoint(train, held):
    """Training meetings must share no speaker and no room with ``held`` (evaluation) meetings."""
    from datatools.ami import SITE_ROOM
    sp = _speakers(train) & _speakers(held)
    rooms = {SITE_ROOM[m[:2]] for m in train} & {SITE_ROOM[m[:2]] for m in held if m.startswith("TS")}
    if sp or rooms:
        raise ValueError(f"training overlaps held-out data: speakers {sorted(sp)}, rooms {sorted(rooms)}")


def stage_ami_train_build(a):
    from datatools.ami import build_meeting_scenes
    meetings = [m for m in AMI_TRAIN if len(list((EXT / "ami" / m).glob(f"{m}.Array1-0*.wav"))) == 8]
    if len(meetings) != len(AMI_TRAIN):
        raise SystemExit(f"missing AMI training meetings: {sorted(set(AMI_TRAIN) - set(meetings))}")
    from datatools.real_sessions import load_registry
    dev = [r["session_id"][4:] for r in load_registry(str(REGISTRY)) if r["split"] == "dev"]
    check_train_disjoint(meetings, dev + list(AMI_MEETINGS) + list(BLIND2_MEETINGS) + list(BLIND3_MEETINGS))
    idx_path = WORK / "ami_train_index.json"
    index = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    for m in meetings:
        if m in index:
            continue
        rng = np.random.default_rng([AMI_TRAIN_SEED, int(m[2:6]), ord(m[-1])])
        index[m] = build_meeting_scenes(str(AMI_ZIP), str(EXT / "ami" / m), m, str(WORK / "ami_train"),
                                        AMI_TRAIN_PER_MEETING, rng)
        idx_path.write_text(json.dumps(index, indent=1), encoding="utf-8")
    summary = {"meetings": meetings, "n_scenes": {m: len(index[m]) for m in meetings},
               "total": sum(len(index[m]) for m in meetings), "n_speakers": len(_speakers(meetings)),
               "disjoint_from": "dev, retired blind, blind2, blind3 (speakers); TNO room"}
    (OUT / "ami_train_build.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary))


def stage_train_v3(a):
    """v3-mix (50 % real AMI-train, 50 % v2 robust synthetic) or v3-real (100 % real)."""
    from training.neural import train_net
    variant = a.variant
    index = json.loads((WORK / "ami_train_index.json").read_text(encoding="utf-8"))
    real = [(r["manifest"], None) for m in AMI_TRAIN for r in index[m]]
    agc = json.loads((EXP / "real_v2" / "agc.json").read_text(encoding="utf-8"))
    (OUT / "agc.json").write_text(json.dumps({**agc, "source": "copied from real_v2 (design §16)"}), encoding="utf-8")
    domains = [{"name": "ami_train", "scenes": real, "weight": 1.0 if variant == "real" else 0.5,
                "channels": list(AMI_TRAIN_CHANNELS), "level_dbfs": agc["input_rms_dbfs"]}]
    if variant == "mix":
        sim = sorted((m.as_posix(), None) for m in (WORK / "train_robust_v2").glob("*/scene_manifest.json"))
        domains.append({"name": "synthetic_robust_v2", "scenes": sim, "weight": 0.5})
    exp = train_net(None, str(OUT / f"model_{variant}"), steps=a.steps, batch=a.batch, seed=a.seed,
                    augment=AugmentConfig(), device=a.device, loader_threads=a.loader_threads, domains=domains,
                    data_identity={"corpus": "AMI ES/IS training meetings (CC BY 4.0)"
                                   + (" + LibriSpeech v2 robust synthetic" if variant == "mix" else ""),
                                   "stage": f"v3-{variant}", "ami_meetings": list(AMI_TRAIN)})
    print(json.dumps({"stage": f"train_v3_{variant}", "domains": exp["data"]["domains"],
                      "train_time_s": exp["metrics"]["train_time_s"],
                      "final_si_sdr_db": exp["metrics"]["train_log"][-1]["si_sdr_db"]}))


def tagged_system(name):
    """'unprocessed' or '<tag>-<model>' with that tag's AGC front end."""
    from training.neural import NeuralSeparator, load_net
    from training.systems import Unprocessed
    if name == "unprocessed":
        return Unprocessed()
    t, m = name.split("-", 1)
    agc = json.loads((EXP / f"real_{t}" / "agc.json").read_text(encoding="utf-8"))["input_rms_dbfs"]
    return NeuralSeparator(load_net(str(EXP / f"real_{t}" / f"model_{m}" / "masknet.pt")), name=name, input_rms_dbfs=agc)


def stage_ami_v3_dev(a):
    """Select the v3 candidate on AMI dev only (rule: higher dev mean SI-SDRi)."""
    from datatools.real_sessions import BlindTestGuard, load_registry
    from evaluation.asr import WhisperAsrBackend
    from evaluation.compare import evaluate_systems
    index = json.loads((WORK / "ami_index.json").read_text(encoding="utf-8"))
    dev_sessions = set(BlindTestGuard(load_registry(str(REGISTRY))).open("dev"))
    dev = [r for r in index["dev"] if f"ami-{r['meeting']}" in dev_sessions]
    models = [m for m in V3_MODELS if (OUT / f"model_{m}" / "masknet.pt").exists()]
    base = "-".join(V3_BASELINE)
    names = ["unprocessed", base] + [f"v3-{m}" for m in models]
    asr = WhisperAsrBackend("small.en", download_root=str(EXT / "whisper"), word_level=True)
    rep = evaluate_systems([(r["manifest"], None) for r in dev], [tagged_system(n) for n in names], names[-1],
                           [n for n in names if n != names[-1]], out_dir=str(OUT / "eval_ami_dev"), asr=asr,
                           transcripts={r["manifest"]: r["transcript"] for r in dev},
                           title="AMI dev: v3 candidates vs v2 base", meta={"asr": asr.name})
    means = rep["summary"]["means"]
    best = max(models, key=lambda m: means[f"v3-{m}"]["si_sdri_db"])
    out = {"dev_means": {k.split("-", 1)[1] if k.startswith("v3-") else k: v for k, v in means.items()},
           "dev_best": best, "baseline": base,
           "dev_vs_base": {m: session_paired(rep["rows"], f"v3-{m}", base, "si_sdri_db") for m in models},
           "rule": "higher AMI dev mean SI-SDRi among v3-mix, v3-real (design §16)"}
    (OUT / "ami_eval.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out))


def stage_asr_diag_dev(a):
    """REQ-402 diagnosis on AMI dev only (design §17): is the WER metric or the separator at fault?

    Adds perfect separation ('oracle': the reference signals) and scores every system
    with the current time-ordered joined WER and with cpWER (per-speaker texts,
    best stream assignment).  No blind session is opened.
    """
    from datatools.ami import scene_speaker_transcripts
    from datatools.real_sessions import BlindTestGuard, load_registry
    from evaluation.asr import WhisperAsrBackend
    from evaluation.compare import evaluate_systems
    from training.systems import OracleReferences
    index = json.loads((WORK / "ami_index.json").read_text(encoding="utf-8"))
    dev_sessions = set(BlindTestGuard(load_registry(str(REGISTRY))).open("dev"))
    dev = [r for r in index["dev"] if f"ami-{r['meeting']}" in dev_sessions]
    spk = scene_speaker_transcripts(str(AMI_ZIP), [r["manifest"] for r in dev])
    for r in dev:                                                    # per-speaker texts rebuild the scene text
        if " ".join(spk[r["manifest"]]) != r["transcript"]:
            raise ValueError(f"speaker texts do not match {r['manifest']}")
    names = ["unprocessed", "v2-base", "v3-mix", "v3-real"]
    systems = [tagged_system(n) for n in names] + [OracleReferences()]
    asr = WhisperAsrBackend("small.en", download_root=str(EXT / "whisper"), word_level=True, device=a.asr_device)
    rep = evaluate_systems([(r["manifest"], None) for r in dev], systems, "v3-mix",
                           [n for n in names + ["oracle"] if n != "v3-mix"], out_dir=str(OUT / "asr_diag_dev"),
                           asr=asr, transcripts={r["manifest"]: r["transcript"] for r in dev},
                           speaker_transcripts=spk, title="AMI dev: WER metric diagnosis (oracle, cpWER)",
                           meta={"asr": asr.name, "device": a.asr_device})
    rows = rep["rows"]
    out = {"n_scenes": len(dev), "means": rep["summary"]["means"],
           "vs_unprocessed": {n: {m: session_paired(rows, n, "unprocessed", m) for m in ("wer", "cpwer")}
                              for n in names[1:] + ["oracle"]},
           "note": "dev only; diagnosis, not a REQ-402 verdict (design §17)"}
    (OUT / "asr_diag_dev.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out))


NSF_DIR = EXT / "notsofar"
BLIND4_OUT = EXP / "blind4_notsofar"
REGISTRY4 = ROOT / "configs" / "real_sessions_blind4_notsofar.csv"
BLIND4_SEED = 400
BLIND4_MIN_SCENES = 10


def blind4_meetings():
    pre = json.loads((BLIND4_OUT / "preregistration.json").read_text(encoding="utf-8"))
    return list(pre["corpus"]["meetings"])


def stage_blind4_build(a):
    """NOTSOFAR-1 blind4 scenes (design §18); refuses unless all 30 pre-registered meetings are complete."""
    from datatools import notsofar
    from datatools.real_sessions import assign_session_splits, load_registry, validate_rows, write_registry
    meetings = blind4_meetings()
    missing = [m for m in meetings if not all((NSF_DIR / m / notsofar.DEVICE / f"ch{c}.wav").exists()
                                              for c in range(notsofar.N_CH))
               or not (NSF_DIR / m / "gt_transcription.json").exists()]
    if missing:
        raise SystemExit(f"blind4 needs all pre-registered meetings; missing {missing}")
    dev = [r for r in load_registry(str(REGISTRY)) if r["split"] == "dev"]
    new = [{k: (";".join(v) if isinstance(v, list) else str(v).lower() if isinstance(v, bool) else v)
            for k, v in notsofar.registry_row(str(NSF_DIR / m), m).items()} for m in meetings]
    rows = assign_session_splits(dev + validate_rows(new), {"dev": 0.5, "blind_test": 0.5})   # leakage check
    write_registry(rows, str(REGISTRY4))
    idx_path = WORK / "blind4_index.json"
    index = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    for m in meetings:
        if m in index:
            continue
        rng = np.random.default_rng([BLIND4_SEED, int(m.split("_")[1])])
        index[m] = notsofar.build_meeting_scenes(str(NSF_DIR / m), m, str(WORK / "blind4"), a.n_ami, rng)
        idx_path.write_text(json.dumps(index, indent=1), encoding="utf-8")
    n = {m: len(index[m]) for m in meetings}
    sessions = [m for m in meetings if n[m] >= BLIND4_MIN_SCENES]
    BLIND4_OUT.mkdir(parents=True, exist_ok=True)
    summary = {"meetings": meetings, "n_scenes": n, "sessions": sessions, "n_sessions": len(sessions),
               "min_scenes_per_session": BLIND4_MIN_SCENES, "registry": str(REGISTRY4.relative_to(ROOT)).replace(os.sep, "/"),
               "rooms": sorted({r["room_id"] for r in rows if r["split"] == "blind_test"})}
    (BLIND4_OUT / "build.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary))


def blind4_verdict(rows, sessions, cand, base, rules_path=None):
    """Design §18 verdicts from scene rows: session means -> approved decision rules (gate.decide)."""
    from evaluation.gate import decide, load_rules
    per = {}                                                          # session -> role -> metric mean
    roles = {"candidate": cand, "fixed_baseline": base, "unprocessed": "unprocessed"}
    for role, sysname in roles.items():
        for s in sessions:
            rr_ = [r for r in rows if r["system"] == sysname and r["scene_id"].rsplit("_", 1)[0] == s]
            per.setdefault(s, {})[role] = {k: float(np.mean([r[k] for r in rr_])) for k in ("wer", "cpwer", "der")}
    rules = load_rules(str(rules_path or ROOT / "configs" / "decision_rules.yaml"))
    gate = decide(rules, per, "candidate")
    by_id = {c["id"]: c for c in gate["comparisons"]}

    def combine(vs):
        return "fail" if "fail" in vs else ("inconclusive" if "inconclusive" in vs else "pass")
    sdr = session_paired(rows, cand, base, "si_sdri_db")
    verdict = {
        "REQ-303": {"rule": f"cand - base SI-SDRi >= +{REQ303_GAIN_DB} dB", **sdr,
                    "verdict": "pass" if sdr["mean_diff"] >= REQ303_GAIN_DB else "fail"},
        "REQ-305": {"rule": "decision_rules wer_vs_fixed_baseline (cpWER)", **by_id["wer_vs_fixed_baseline"],
                    "verdict": by_id["wer_vs_fixed_baseline"]["verdict"]},
        "REQ-402": {"rule": "decision_rules wer_vs_unprocessed (cpWER) and der_vs_unprocessed",
                    "cpwer": by_id["wer_vs_unprocessed"], "der": by_id["der_vs_unprocessed"],
                    "verdict": combine([by_id["wer_vs_unprocessed"]["verdict"], by_id["der_vs_unprocessed"]["verdict"]])},
        "REQ-405": {"regression": gate["regression"], "verdict": gate["regression"]["verdict"] if gate["regression"] else None},
    }
    return gate, verdict, rules


def stage_blind4_eval(a):
    """Open blind4 once for the frozen v3-mix and apply the approved decision rules (design §18)."""
    import hashlib
    from datatools.real_sessions import BlindTestGuard, load_registry
    from evaluation.asr import WhisperAsrBackend
    from evaluation.compare import evaluate_systems
    pre = json.loads((BLIND4_OUT / "preregistration.json").read_text(encoding="utf-8"))
    cand, base = pre["candidate"]["system"], pre["baseline"]
    t, m = cand.split("-", 1)
    sha = hashlib.sha256((EXP / f"real_{t}" / f"model_{m}" / "masknet.pt").read_bytes()).hexdigest()
    if not sha.startswith(pre["candidate"]["sha256_prefix"]):
        raise SystemExit("candidate checkpoint differs from the pre-registered one")
    build = json.loads((BLIND4_OUT / "build.json").read_text(encoding="utf-8"))
    guard = BlindTestGuard(load_registry(str(REGISTRY4)))
    guard.freeze(sha)
    opened = guard.open("blind_test", sha)
    log_path = BLIND4_OUT / "access_log.json"
    if log_path.exists():
        raise PermissionError("blind4 was already opened once; it is not reopened (design §18)")
    log_path.write_text(json.dumps([{"frozen_sha256": sha, "candidate": cand, "sessions": opened}], indent=1),
                        encoding="utf-8")
    index = json.loads((WORK / "blind4_index.json").read_text(encoding="utf-8"))
    sessions = [s for s in build["sessions"] if f"nsf-{s}" in opened]
    recs = [r for s in sessions for r in index[s]]
    names = ["unprocessed", cand, base, "v3-real", "v1-base"]
    asr = WhisperAsrBackend("small.en", download_root=str(EXT / "whisper"), word_level=True, device=a.asr_device)
    rep = evaluate_systems([(r["manifest"], None) for r in recs], [tagged_system(n) for n in names], cand,
                           [n for n in names if n != cand], out_dir=str(BLIND4_OUT / "eval"), asr=asr,
                           transcripts={r["manifest"]: r["transcript"] for r in recs},
                           speaker_transcripts={r["manifest"]: r["speaker_transcripts"] for r in recs},
                           title=f"blind4 NOTSOFAR-1 (frozen candidate {cand})",
                           meta={"frozen_sha256": sha, "asr": asr.name, "device": a.asr_device})
    blind4_write_result(rep, sessions, cand, base, sha, names)


def blind4_write_result(rep, sessions, cand, base, sha, names, out_dir=None):
    """Verdict from the evaluated rows under the approved rules; pure post-processing (no audio, no model)."""
    out_dir = Path(out_dir) if out_dir is not None else BLIND4_OUT
    rows = rep["rows"]
    gate, verdict, rules = blind4_verdict(rows, sessions, cand, base)
    out = {"candidate": cand, "baseline": base, "frozen_sha256": sha, "n_sessions": len(sessions), "sessions": sessions,
           "n_scenes": rep["summary"]["n_scenes"], "means": rep["summary"]["means"], "gate": gate,
           "reference_pairs": {n: {k: session_paired(rows, n, base, k) for k in ("si_sdri_db", "cpwer")}
                               for n in names if n not in (cand, base)},
           "verdict": verdict, "rules_status": rules.get("status"), "rules_amendments": rules.get("amendments")}
    # default=str: YAML amendment dates load as datetime.date (the 2026-11-24 run crashed here after evaluating)
    (out_dir / "result.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, default=str))
    return out


def stage_blind4_finalize(a):
    """Recompute result.json from the saved eval/comparison.json of the single blind4 opening.

    Reads only the rows written by that run; it neither loads audio nor runs a model, so blind4 is not reopened.
    """
    log = json.loads((BLIND4_OUT / "access_log.json").read_text(encoding="utf-8"))
    rep = json.loads((BLIND4_OUT / "eval" / "comparison.json").read_text(encoding="utf-8"))
    if len(log) != 1 or rep["meta"]["frozen_sha256"] != log[0]["frozen_sha256"]:
        raise SystemExit("comparison.json does not belong to the single logged blind4 opening")
    pre = json.loads((BLIND4_OUT / "preregistration.json").read_text(encoding="utf-8"))
    cand, base = pre["candidate"]["system"], pre["baseline"]
    build = json.loads((BLIND4_OUT / "build.json").read_text(encoding="utf-8"))
    sessions = [s for s in build["sessions"] if f"nsf-{s}" in log[0]["sessions"]]
    names = ["unprocessed", cand, base, "v3-real", "v1-base"]
    if {r["system"] for r in rep["rows"]} != set(names):
        raise SystemExit("unexpected systems in comparison.json")
    blind4_write_result(rep, sessions, cand, base, log[0]["frozen_sha256"], names)


# --- v4: NOTSOFAR real training, dev1 selection, new-site blind5 (design §19) -------------------------------------
NSF4_DIR = EXT / "notsofar_v4"
OUT_V4 = EXP / "real_v4"
BLIND5_OUT = EXP / "blind5_notsofar"
REGISTRY5 = ROOT / "configs" / "real_sessions_blind5_notsofar.csv"
V4_SEEDS = {"train": 410, "dev1": 420, "blind5": 500}
V4_DIRS = {"train": "train", "dev1": "dev1", "blind5": "eval"}


def v4_prereg():
    return json.loads((BLIND5_OUT / "preregistration.json").read_text(encoding="utf-8"))


def v4_meetings(pre=None):
    pre = pre or v4_prereg()
    return {"train": list(pre["train"]["meetings"]), "dev1": list(pre["selection_dev"]["meetings"]),
            "blind5": list(pre["blind5"]["meetings"])}


def _nsf_rows(part, meetings, split):
    from datatools import notsofar
    from datatools.real_sessions import validate_rows
    return validate_rows([{k: (";".join(v) if isinstance(v, list) else str(v).lower() if isinstance(v, bool) else v)
                           for k, v in notsofar.registry_row(str(NSF4_DIR / V4_DIRS[part] / m), m, split).items()}
                          for m in meetings])


def stage_v4_build(a):
    """Scenes for NOTSOFAR train / dev1 / blind5 (design §19); blind5 is built but no system is run on it."""
    from datatools import notsofar
    from datatools.real_sessions import assign_session_splits, write_registry
    pre = v4_prereg()
    parts = v4_meetings(pre)
    missing = [f"{p}/{m}" for p, ms in parts.items() for m in ms
               if not (NSF4_DIR / V4_DIRS[p] / m / "gt_transcription.json").exists()
               or not all((NSF4_DIR / V4_DIRS[p] / m / notsofar.DEVICE / f"ch{c}.wav").exists() for c in range(notsofar.N_CH))]
    if missing:
        raise SystemExit(f"v4 needs every pre-registered meeting; missing {missing[:5]} ({len(missing)})")
    blind = _nsf_rows("blind5", parts["blind5"], "blind_test")
    # leakage checks: blind5 shares no room or speaker with training, nor with dev1 (train and dev1 do share speakers,
    # declared in design §19; dev1 is used for selection only)
    assign_session_splits(_nsf_rows("train", parts["train"], "dev") + blind, {"dev": 0.5, "blind_test": 0.5})
    rows = assign_session_splits(_nsf_rows("dev1", parts["dev1"], "dev") + blind, {"dev": 0.5, "blind_test": 0.5})
    write_registry(rows, str(REGISTRY5))
    idx_path = WORK / "v4_index.json"
    index = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    for p, ms in parts.items():
        index.setdefault(p, {})
        for m in ms:
            if m in index[p]:
                continue
            rng = np.random.default_rng([V4_SEEDS[p], int(m.split("_")[1])])
            index[p][m] = notsofar.build_meeting_scenes(str(NSF4_DIR / V4_DIRS[p] / m), m, str(WORK / f"v4_{p}"),
                                                        a.n_ami, rng)
            idx_path.write_text(json.dumps(index, indent=1), encoding="utf-8")
    n = {p: {m: len(index[p][m]) for m in ms} for p, ms in parts.items()}
    min_sc = pre["blind5"]["min_scenes_per_session"]
    sessions = [m for m in parts["blind5"] if n["blind5"][m] >= min_sc]
    OUT_V4.mkdir(parents=True, exist_ok=True)
    (OUT_V4 / "build.json").write_text(json.dumps(
        {"train": {"meetings": len(parts["train"]), "scenes": sum(n["train"].values())},
         "dev1": {"meetings": len(parts["dev1"]), "scenes": sum(n["dev1"].values()),
                  "sessions": [m for m in parts["dev1"] if n["dev1"][m] > 0]},
         "n_scenes": {p: n[p] for p in ("train", "dev1")}}, indent=1), encoding="utf-8")
    summary = {"meetings": parts["blind5"], "n_scenes": n["blind5"], "sessions": sessions, "n_sessions": len(sessions),
               "min_scenes_per_session": min_sc, "registry": str(REGISTRY5.relative_to(ROOT)).replace(os.sep, "/"),
               "rooms": sorted({r["room_id"] for r in rows if r["split"] == "blind_test"})}
    (BLIND5_OUT / "build.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps({"train_scenes": sum(n["train"].values()), "dev1_scenes": sum(n["dev1"].values()),
                      "blind5_sessions": len(sessions), "blind5_scenes": sum(n["blind5"][m] for m in sessions)}))


def stage_train_v4(a):
    """v4-nsf (100 % NOTSOFAR train) or v4-real (50 % NOTSOFAR train + 50 % AMI ES/IS train), design §19."""
    from training.neural import train_net
    pre = v4_prereg()
    variant = a.variant
    if f"v4-{variant}" not in pre["variants"]:
        raise SystemExit(f"v4 variant must be one of {sorted(pre['variants'])}")
    index = json.loads((WORK / "v4_index.json").read_text(encoding="utf-8"))
    nsf = [(r["manifest"], None) for m in pre["train"]["meetings"] for r in index["train"][m]]
    OUT_V4.mkdir(parents=True, exist_ok=True)
    agc = json.loads((EXP / "real_v2" / "agc.json").read_text(encoding="utf-8"))
    (OUT_V4 / "agc.json").write_text(json.dumps({**agc, "source": "copied from real_v2 (design §19)"}), encoding="utf-8")
    domains = [{"name": "notsofar_train", "scenes": nsf, "weight": 1.0 if variant == "nsf" else 0.5,
                "channels": list(pre["train"]["channels"]), "level_dbfs": agc["input_rms_dbfs"]}]
    if variant == "real":
        ami = json.loads((WORK / "ami_train_index.json").read_text(encoding="utf-8"))
        domains.append({"name": "ami_train", "scenes": [(r["manifest"], None) for m in AMI_TRAIN for r in ami[m]],
                        "weight": 0.5, "channels": list(AMI_TRAIN_CHANNELS), "level_dbfs": agc["input_rms_dbfs"]})
    exp = train_net(None, str(OUT_V4 / f"model_{variant}"), steps=a.steps, batch=a.batch, seed=a.seed,
                    augment=AugmentConfig(), device=a.device, loader_threads=a.loader_threads, domains=domains,
                    data_identity={"corpus": "NOTSOFAR-1 train (CC BY 4.0)" + (" + AMI ES/IS train" if variant == "real" else ""),
                                   "stage": f"v4-{variant}", "nsf_meetings": pre["train"]["meetings"]})
    print(json.dumps({"stage": f"train_v4_{variant}", "domains": exp["data"]["domains"],
                      "train_time_s": exp["metrics"]["train_time_s"],
                      "final_si_sdr_db": exp["metrics"]["train_log"][-1]["si_sdr_db"]}))


def session_means(rows, system, metric):
    per = {}
    for r in rows:
        if r["system"] == system and metric in r:
            per.setdefault(r["scene_id"].rsplit("_", 1)[0], []).append(r[metric])
    return float(np.mean([np.mean(v) for v in per.values()])), len(per)


def v4_select(rows, candidates, base):
    """Design §19 rule: lowest dev1 session-mean cpWER among candidates with SI-SDRi above v2-base; ties -> SI-SDRi."""
    table = {}
    for c in candidates:
        cp, n = session_means(rows, c, "cpwer")
        sdr = session_paired(rows, c, base, "si_sdri_db")
        table[c] = {"cpwer": cp, "n_sessions": n, "si_sdri_vs_base": sdr, "eligible": sdr["mean_diff"] > 0}
    ok = [c for c in candidates if table[c]["eligible"]]
    best = min(ok, key=lambda c: (table[c]["cpwer"], -table[c]["si_sdri_vs_base"]["mean_diff"])) if ok else None
    return best, table


def stage_v4_dev_select(a):
    """Select the v4 candidate on NOTSOFAR dev1 only (design §19) and record its sha256 for blind5."""
    import hashlib
    from evaluation.asr import WhisperAsrBackend
    from evaluation.compare import evaluate_systems
    pre = v4_prereg()
    index = json.loads((WORK / "v4_index.json").read_text(encoding="utf-8"))
    recs = [r for m in pre["selection_dev"]["meetings"] for r in index["dev1"][m]]
    cands = [c for c in pre["candidates"]
             if (EXP / f"real_{c.split('-')[0]}" / f"model_{c.split('-', 1)[1]}" / "masknet.pt").exists()]
    if cands != pre["candidates"]:
        raise SystemExit(f"missing candidate checkpoints: {sorted(set(pre['candidates']) - set(cands))}")
    base = pre["baseline"]
    names = ["unprocessed", base] + cands
    asr = WhisperAsrBackend("small.en", download_root=str(EXT / "whisper"), word_level=True, device=a.asr_device)
    rep = evaluate_systems([(r["manifest"], None) for r in recs], [tagged_system(n) for n in names], cands[0],
                           [n for n in names if n != cands[0]], out_dir=str(OUT_V4 / "eval_dev1"), asr=asr,
                           transcripts={r["manifest"]: r["transcript"] for r in recs},
                           speaker_transcripts={r["manifest"]: r["speaker_transcripts"] for r in recs},
                           title="NOTSOFAR dev1: v4 selection (design §19)", meta={"asr": asr.name, "device": a.asr_device})
    best, table = v4_select(rep["rows"], cands, base)
    if best is None:
        raise SystemExit("no candidate beats v2-base on dev1 SI-SDRi; nothing to freeze")
    t, m = best.split("-", 1)
    sha = hashlib.sha256((EXP / f"real_{t}" / f"model_{m}" / "masknet.pt").read_bytes()).hexdigest()
    out = {"rule": pre["selection_rule"], "candidates": table, "selected": best, "selected_sha256": sha,
           "means": rep["summary"]["means"], "n_scenes": len(recs),
           "unprocessed_cpwer": session_means(rep["rows"], "unprocessed", "cpwer")[0]}
    (OUT_V4 / "dev1_select.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out))


def stage_blind5_eval(a):
    """Open blind5 once for the dev1-selected candidate and apply the approved rules (design §19)."""
    import hashlib
    from datatools.real_sessions import BlindTestGuard, load_registry
    from evaluation.asr import WhisperAsrBackend
    from evaluation.compare import evaluate_systems
    pre = v4_prereg()
    sel = json.loads((OUT_V4 / "dev1_select.json").read_text(encoding="utf-8"))
    cand, base = sel["selected"], pre["baseline"]
    t, m = cand.split("-", 1)
    sha = hashlib.sha256((EXP / f"real_{t}" / f"model_{m}" / "masknet.pt").read_bytes()).hexdigest()
    if sha != sel["selected_sha256"]:
        raise SystemExit("candidate checkpoint changed after dev1 selection")
    build = json.loads((BLIND5_OUT / "build.json").read_text(encoding="utf-8"))
    log_path = BLIND5_OUT / "access_log.json"
    if log_path.exists():
        raise PermissionError("blind5 was already opened once; it is not reopened (design §19)")
    guard = BlindTestGuard(load_registry(str(REGISTRY5)))
    guard.freeze(sha)
    opened = guard.open("blind_test", sha)
    log_path.write_text(json.dumps([{"frozen_sha256": sha, "candidate": cand, "sessions": opened}], indent=1),
                        encoding="utf-8")
    index = json.loads((WORK / "v4_index.json").read_text(encoding="utf-8"))["blind5"]
    sessions = [s for s in build["sessions"] if f"nsf-{s}" in opened]
    recs = [r for s in sessions for r in index[s]]
    names = ["unprocessed", cand, base] + [n for n in pre["references"] if n not in ("unprocessed", cand, base)]
    asr = WhisperAsrBackend("small.en", download_root=str(EXT / "whisper"), word_level=True, device=a.asr_device)
    rep = evaluate_systems([(r["manifest"], None) for r in recs], [tagged_system(n) for n in names], cand,
                           [n for n in names if n != cand], out_dir=str(BLIND5_OUT / "eval"), asr=asr,
                           transcripts={r["manifest"]: r["transcript"] for r in recs},
                           speaker_transcripts={r["manifest"]: r["speaker_transcripts"] for r in recs},
                           title=f"blind5 NOTSOFAR-1 new rooms (frozen candidate {cand})",
                           meta={"frozen_sha256": sha, "asr": asr.name, "device": a.asr_device})
    blind4_write_result(rep, sessions, cand, base, sha, names, out_dir=BLIND5_OUT)


def blind3_meetings():
    return [m for m in BLIND3_MEETINGS if len(list((EXT / "ami" / m).glob(f"{m}.Array1-0*.wav"))) == 8]


def stage_ami_blind3_build(a):
    from datatools.ami import build_meeting_scenes
    meetings = blind3_meetings()
    if meetings != list(BLIND3_MEETINGS):
        raise SystemExit(f"blind3 needs all 16 meetings on disk; missing {sorted(set(BLIND3_MEETINGS) - set(meetings))}")
    check_train_disjoint(list(AMI_TRAIN), meetings)
    rows = blind2_registry(meetings, REGISTRY3)
    idx_path = WORK / "ami_blind3_index.json"
    index = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    for m in meetings:
        if m in index:
            continue
        rng = np.random.default_rng([BLIND2_SEED, int(m[2:6]), ord(m[-1])])
        index[m] = build_meeting_scenes(str(AMI_ZIP), str(EXT / "ami" / m), m, str(WORK / "ami_blind3"), a.n_ami, rng)
        idx_path.write_text(json.dumps(index, indent=1), encoding="utf-8")
    BLIND3_OUT.mkdir(parents=True, exist_ok=True)
    summary = {"meetings": meetings, "n_sessions": len(meetings), "n_scenes": {m: len(index[m]) for m in meetings},
               "registry": str(REGISTRY3.relative_to(ROOT)).replace(os.sep, "/"),
               "splits": {r["session_id"]: r["split"] for r in rows}}
    (BLIND3_OUT / "build.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary))


def stage_ami_blind3_eval(a):
    import hashlib
    from datatools.real_sessions import BlindTestGuard, load_registry
    from evaluation.asr import WhisperAsrBackend
    from evaluation.compare import evaluate_systems
    sel = json.loads((EXP / "real_v3" / "ami_eval.json").read_text(encoding="utf-8"))
    model = sel["dev_best"]
    cand, base = f"v3-{model}", "-".join(V3_BASELINE)
    sha = hashlib.sha256((EXP / "real_v3" / f"model_{model}" / "masknet.pt").read_bytes()).hexdigest()
    guard = BlindTestGuard(load_registry(str(REGISTRY3)))
    guard.freeze(sha)
    sessions = guard.open("blind_test", sha)
    log_path = BLIND3_OUT / "access_log.json"
    if log_path.exists():
        raise PermissionError("blind3 was already opened once; it is not reopened (design §16)")
    BLIND3_OUT.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps([{"frozen_sha256": sha, "candidate": cand, "sessions": sessions}], indent=1),
                        encoding="utf-8")
    index = json.loads((WORK / "ami_blind3_index.json").read_text(encoding="utf-8"))
    names = ["unprocessed", cand, base] + [f"v3-{m}" for m in V3_MODELS if m != model
                                            and (EXP / "real_v3" / f"model_{m}" / "masknet.pt").exists()]
    names += [n for n in ("v2-cal", "v1-base") if (EXP / f"real_{n.split('-')[0]}" / f"model_{n.split('-')[1]}" / "masknet.pt").exists()]
    recs = [r for m, rs in index.items() if f"ami-{m}" in sessions for r in rs]
    asr = WhisperAsrBackend("small.en", download_root=str(EXT / "whisper"), word_level=True)
    rep = evaluate_systems([(r["manifest"], None) for r in recs], [tagged_system(n) for n in names], cand,
                           [n for n in names if n != cand], out_dir=str(BLIND3_OUT / "eval"), asr=asr,
                           transcripts={r["manifest"]: r["transcript"] for r in recs},
                           title=f"AMI blind3 (frozen candidate {cand})", meta={"frozen_sha256": sha, "asr": asr.name})
    rows, means = rep["rows"], rep["summary"]["means"]
    n_sess = len(sessions)
    sdr = session_paired(rows, cand, base, "si_sdri_db")
    w = session_paired(rows, cand, base, "wer")
    wg = session_paired(rows, cand, base, "wer_gated")
    u_wer, c_wer = means["unprocessed"]["wer"], means[cand]["wer"]
    wer_rel = (c_wer - u_wer) / u_wer if u_wer > 0 else float("nan")
    der_pp = 100 * (means[cand]["der"] - means["unprocessed"]["der"])
    enough = n_sess >= MIN_SESSIONS
    verdict = {
        "REQ-303": {"rule": f"cand - base SI-SDRi >= +{REQ303_GAIN_DB} dB", **sdr, "met": sdr["mean_diff"] >= REQ303_GAIN_DB},
        "REQ-305": {"rule": f"cand - base WER <= {REQ305_PP} pp, session CI upper < 0, >= {MIN_SESSIONS} sessions",
                    "mean_diff_pp": 100 * w["mean_diff"], "ci95_pp": [100 * x for x in w["ci95"]], "n_sessions": n_sess,
                    "met": (100 * w["mean_diff"] <= REQ305_PP and w["ci95"][1] < 0) if enough else None,
                    "withheld": not enough,
                    "gated_secondary_pp": {"mean": 100 * wg["mean_diff"], "ci95": [100 * x for x in wg["ci95"]]}},
        "REQ-402": {"rule": f"WER relative <= -15 % and DER <= -5.0 pp vs unprocessed, >= {MIN_SESSIONS} sessions",
                    "wer_rel": wer_rel, "der_pp": der_pp,
                    "met": (wer_rel <= REQ402_WER_REL and der_pp <= REQ402_DER_PP) if enough else None,
                    "withheld": not enough},
    }
    out = {"candidate": cand, "dev_selection": sel, "baseline": base, "frozen_sha256": sha, "n_sessions": n_sess,
           "sessions": sessions, "n_scenes": len(recs), "means": means,
           "reference_pairs": {n: session_paired(rows, n, base, "si_sdri_db") for n in names[2:] if n != base},
           "verdict": verdict}
    (BLIND3_OUT / "result.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=("train_base", "train_robust", "train_cal", "asr", "heldout",
                                      "ami_build", "ami_eval", "ami_adapt", "asr_gate",
                                      "ami_blind2_build", "ami_blind2_eval", "ami_train_build", "train_v3",
                                      "ami_v3_dev", "ami_blind3_build", "ami_blind3_eval", "asr_diag_dev", "blind4_build", "blind4_eval",
                                      "blind4_finalize", "v4_build", "train_v4", "v4_dev_select", "blind5_eval"))
    ap.add_argument("--variant", choices=("mix", "real", "nsf"), default="mix",
                    help="train_v3 model mix|real (design §16); train_v4 model nsf|real (design §19)")
    ap.add_argument("--n-ami", type=int, default=40, help="scenes per AMI meeting")
    ap.add_argument("--generate-only", action="store_true", help="render training scenes, do not train")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--asr-device", default="cpu", help="Whisper device for asr_diag_dev")
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--loader-threads", type=int, default=0, help="thread-pool batch builder (use with --device cuda)")
    ap.add_argument("--n-train", type=int, default=1200)
    ap.add_argument("--n-test", type=int, default=60)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tag", choices=tuple(TAGS), default="v1")
    a = ap.parse_args()
    global OUT, TAG
    TAG = TAGS[a.tag]
    OUT = ROOT / "reports" / "experiments" / f"real_{a.tag}"
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    if a.stage in ("train_v3", "train_v4"):
        (stage_train_v3 if a.stage == "train_v3" else stage_train_v4)(a)
        if a.device.startswith("cuda"):
            _exit_without_teardown(0)
    elif a.stage.startswith("train_"):
        stage_train(a.stage[6:], a)
        if a.device.startswith("cuda") and not a.generate_only:
            # torch 2.15+cu132 / cuDNN 9.26: a multi-layer LSTM trained with dropout aborts
            # in process teardown (0xC0000409) after all outputs are written, even under
            # os._exit (DLL detach still runs).  Skip teardown so the exit code reflects
            # the stage result.
            _exit_without_teardown(0)
    elif a.stage == "asr":
        stage_asr(a)
    elif a.stage == "ami_build":
        stage_ami_build(a)
    elif a.stage == "ami_eval":
        stage_ami_eval(a)
    elif a.stage == "ami_adapt":
        stage_ami_adapt(a)
    elif a.stage == "asr_gate":
        stage_asr_gate(a)
    elif a.stage == "ami_blind2_build":
        stage_ami_blind2_build(a)
    elif a.stage == "ami_blind2_eval":
        stage_ami_blind2_eval(a)
    elif a.stage == "ami_train_build":
        stage_ami_train_build(a)
    elif a.stage == "ami_v3_dev":
        stage_ami_v3_dev(a)
    elif a.stage == "ami_blind3_build":
        stage_ami_blind3_build(a)
    elif a.stage == "ami_blind3_eval":
        stage_ami_blind3_eval(a)
    elif a.stage in ("asr_diag_dev", "blind4_eval"):
        (stage_asr_diag_dev if a.stage == "asr_diag_dev" else stage_blind4_eval)(a)
        if a.asr_device == "cuda":
            _exit_without_teardown(0)
    elif a.stage == "v4_build":
        stage_v4_build(a)
    elif a.stage in ("v4_dev_select", "blind5_eval"):
        (stage_v4_dev_select if a.stage == "v4_dev_select" else stage_blind5_eval)(a)
        if a.asr_device == "cuda":
            _exit_without_teardown(0)
    elif a.stage == "blind4_finalize":
        stage_blind4_finalize(a)
    elif a.stage == "blind4_build":
        stage_blind4_build(a)
    else:
        stage_heldout(a)


if __name__ == "__main__":
    main()
