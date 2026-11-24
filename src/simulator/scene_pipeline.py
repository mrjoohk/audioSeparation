"""
Static scene rendering pipeline with a training-data contract.

Design: design_md/W100000/W1_audit_remediation_design.md §2–§4 (F-01, F-02, F-08, F-09).

Outputs per scene (all on one sample grid, index 0 = scene start / emission time):

    mixture__{rec}.wav            observed mixture after the capture chain  [C, T]
    reference__{src}__{rec}.wav   separation target: source image at the mic
                                  position *before* device degradation       [S, C, T]
    noise__{rec}.wav              device self-noise as added to the mixture  [C, T]
    dry__{src}.wav                dry signal placed on the scene timeline    [S, N_dry]
    rir__{src}__{rec}.wav         room impulse response                     [S, C, L]
    params.json, acoustic_summary.json, scene_manifest.json (schema 2.0.0)

The scene is written to a staging directory, QC-checked, and committed
atomically; failures are quarantined (``scene_io.SceneStaging``).
"""
from __future__ import annotations

import copy
import math
import os
import time
import warnings
import zlib
from math import gcd
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import fftconvolve, resample_poly

from simulator.types import AcousticSummary, MicSpec, SceneConfig
from simulator.uf.w151_config import (
    SceneConfigValidator,
    derive_subsystem_seeds,
    scene_config_to_dict,
)
from simulator.config_resolver import (
    VALIDATED_QUANTITIES,
    asset_hashes,
    check_profile,
    render_fingerprint,
    resolve_config,
    strip_private,
)
from datatools.vad import (
    overlap_ratio as vad_overlap_ratio,
    segments_to_mask,
    shift_segments,
    vad_segments,
)
from simulator.scene_io import (
    AUDIO_ENCODING,
    MANIFEST_NAME,
    MANIFEST_SCHEMA_VERSION_V2,
    RENDERER_VERSION,
    SceneQCError,
    SceneStaging,
    UnsupportedProfileError,
    now_iso,
    read_wav,
    sha256_file,
)

SYNTHETIC_DRY_STD = 0.01            # white-noise stand-in for speech (−40 dBFS RMS)
SUM_TOLERANCE_REL = 1e-4            # float32 render path vs float64 component sum
PRE_ARRIVAL_TOLERANCE_REL = 1e-6    # energy allowed before the declared arrival
EDGE_MARGIN_M = 1e-3                # array-error perturbation is kept this far inside


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_for(*parts) -> int:
    return zlib.crc32(":".join(str(p) for p in parts).encode("utf-8")) & 0x7FFFFFFF


def _to_float(data: np.ndarray) -> np.ndarray:
    """Integer PCM → float in [-1, 1); float passes through."""
    if np.issubdtype(data.dtype, np.floating):
        return data.astype(np.float64)
    if data.dtype == np.uint8:
        return (data.astype(np.float64) - 128.0) / 128.0
    info = np.iinfo(data.dtype)
    return data.astype(np.float64) / float(-info.min)


def _load_signal(path: str, fs: int) -> Tuple[np.ndarray, dict]:
    file_fs, data = read_wav(path)
    x = _to_float(data)
    meta = {"kind": "file", "path": path, "sha256": sha256_file(path)}
    if x.ndim == 2:
        x = x.mean(axis=1)
        meta["downmixed_channels"] = int(data.shape[1])
    if file_fs != fs:
        g = gcd(int(fs), int(file_fs))
        x = resample_poly(x, fs // g, file_fs // g)
        meta["resampled_from"] = int(file_fs)
    return x, meta


def _shift(x: np.ndarray, k: int) -> np.ndarray:
    """Delay (k > 0) or advance (k < 0) along the last axis with zero fill."""
    if k == 0:
        return x
    out = np.zeros_like(x)
    if k > 0:
        out[..., k:] = x[..., :-k]
    else:
        out[..., :k] = x[..., -k:]
    return out


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if x.size else 0.0


def _position_of(ent: dict) -> Optional[List[float]]:
    pos = ent.get("position")
    if pos is None:
        pos = (ent.get("motion") or {}).get("position")
    return None if pos is None else [float(v) for v in pos]


# ---------------------------------------------------------------------------
# Stage: dry sources on the scene timeline (F-02)
# ---------------------------------------------------------------------------

def prepare_sources(
    resolved: dict,
    n_dry: int,
    overrides: Optional[Dict[str, np.ndarray]] = None,
) -> Tuple[np.ndarray, List[dict]]:
    """Place every source's dry signal on the timeline ``[0, n_dry)``.

    Returns:
        (dry float64[S, n_dry], per-source metadata)
    """
    fs = int(resolved["sample_rate"])
    seed = int(resolved["seed"])
    sources = resolved["sources"]
    dry = np.zeros((len(sources), n_dry), dtype=np.float64)
    metas: List[dict] = []
    for i, src in enumerate(sources):
        sid = src["source_id"]
        onset = int(round(float(src.get("onset_s", 0.0)) * fs))
        if not (0 <= onset < n_dry):
            raise ValueError(
                f"source {sid}: onset_s={src.get('onset_s')} is outside the scene "
                f"duration ({n_dry / fs:.3f} s)."
            )
        if overrides and sid in overrides:
            sig = np.asarray(overrides[sid], dtype=np.float64).ravel()
            meta = {"kind": "array", "sha256": None}
        elif src.get("signal_path"):
            sig, meta = _load_signal(src["signal_path"], fs)
        else:
            rng = np.random.default_rng(_seed_for(seed, "dry", sid))
            sig = rng.standard_normal(n_dry - onset) * SYNTHETIC_DRY_STD
            meta = {"kind": "synthetic_white_noise", "sha256": None}
        if not np.all(np.isfinite(sig)):
            raise ValueError(f"source {sid}: dry signal contains non-finite values.")
        if src.get("level_dbfs") is not None:
            target = 10.0 ** (float(src["level_dbfs"]) / 20.0) / math.sqrt(2.0)  # AES17
            cur = _rms(sig)
            if cur > 0:
                sig = sig * (target / cur)
            meta["level_dbfs"] = float(src["level_dbfs"])
        n_avail = n_dry - onset
        n_place = min(len(sig), n_avail)
        dry[i, onset:onset + n_place] = sig[:n_place]
        meta.update({
            "source_id": sid,
            "onset_sample": onset,
            "n_samples": int(n_place),
            "truncated": bool(len(sig) > n_avail),
        })
        metas.append(meta)
    return dry, metas


# ---------------------------------------------------------------------------
# Stage: array errors before propagation (F-09)
# ---------------------------------------------------------------------------

def apply_array_errors(resolved: dict) -> Tuple[dict, List[dict], List[str]]:
    """Perturb receiver positions and draw per-channel clock shifts.

    Returns:
        (effective_config, receiver_records, approximations)
    """
    eff = copy.deepcopy(resolved)
    arr = (resolved.get("impairments") or {}).get("array_errors") or {}
    sigma = float(arr.get("position_sigma_m", 0.0))
    kmax = int(arr.get("max_clock_skew_samples", 0))
    seed = derive_subsystem_seeds(int(resolved["seed"]), ["array"])["array"]
    rng = np.random.default_rng(seed)
    dims = (resolved.get("room") or {}).get("dimensions", {})
    hi = np.array([dims.get("L", np.inf), dims.get("H", np.inf), dims.get("W", np.inf)], float)
    records: List[dict] = []
    approx: List[str] = []
    for rec in eff["receivers"]:
        nominal = _position_of(rec)
        effective = nominal
        if nominal is not None and sigma > 0.0:
            cand = np.asarray(nominal) + rng.normal(0.0, sigma, 3)
            clamped = np.clip(cand, EDGE_MARGIN_M, hi - EDGE_MARGIN_M)
            if not np.allclose(clamped, cand):
                approx.append(f"receiver {rec['receiver_id']}: perturbed position clamped into room")
            effective = clamped.tolist()
            rec["position"] = effective
            rec.setdefault("motion", {"type": "static"})
            rec["motion"].pop("position", None)
        shift = int(rng.integers(-kmax, kmax + 1)) if kmax > 0 else 0
        records.append({
            "receiver_id": rec["receiver_id"],
            "nominal_position": nominal,
            "effective_position": effective,
            "clock_shift_samples": shift,
        })
    return eff, records, approx



# ---------------------------------------------------------------------------
# Receiver models, binaural expansion, dynamic rendering (stage 6)
# ---------------------------------------------------------------------------

BINAURAL_HALF_WIDTH = 64      # half of the 128-tap synthetic HRTF FIR
RERENDER_THRESHOLD_M = 0.05   # REQ-W06: new RIR when a source/mic moves more than 5 cm


def expand_binaural(eff: dict, rec_records: List[dict]) -> Tuple[dict, List[dict]]:
    """Replace each binaural receiver by two ear channels ``<id>.L`` / ``<id>.R``."""
    out_recs, out_records = [], []
    ref = eff.get("reference_receiver")
    for rec, record in zip(eff["receivers"], rec_records):
        if rec.get("binaural"):
            for ear in ("L", "R"):
                r2 = copy.deepcopy(rec)
                r2.pop("binaural", None)
                r2["receiver_id"] = f"{rec['receiver_id']}.{ear}"
                r2["ear"] = ear
                r2["head"] = rec["receiver_id"]
                out_recs.append(r2)
                out_records.append({**record, "receiver_id": r2["receiver_id"], "ear": ear,
                                    "head": rec["receiver_id"],
                                    "hrtf": dict(rec["hrtf"]) if rec.get("hrtf") else {"model": "synthetic_sphere"}})
            if ref == rec["receiver_id"]:
                eff["reference_receiver"] = f"{rec['receiver_id']}.L"
        else:
            out_recs.append(rec)
            out_records.append(record)
    eff["receivers"] = out_recs
    return eff, out_records


def receiver_models(eff: dict, fs: int) -> Dict[str, object]:
    from simulator.receiver_models import (
        ReceiverModel, binaural_response, diffuse_gain, directivity_response,
    )
    models = {}
    for r in eff["receivers"]:
        yaw = float(r.get("yaw_deg", 0.0))
        if r.get("ear"):
            models[r["receiver_id"]] = ReceiverModel(binaural_response(r["ear"], yaw, fs, hrtf=r.get("hrtf")),
                                                     tail_salt=r["ear"])
        elif str(r.get("pattern", "omni")) != "omni":
            pat = str(r["pattern"])
            models[r["receiver_id"]] = ReceiverModel(directivity_response(pat, yaw), tail_gain=diffuse_gain(pat))
    return models


def _delay_at(trace: np.ndarray, n: int, hop: int) -> int:
    return int(trace[min(max(n, 0) // hop, len(trace) - 1)]) if len(trace) > 1 else int(trace[0])


def shift_segments_varying(segs, trace: np.ndarray, hop: int, limit: int, extra: int = 0):
    """Map emission-time segments to arrival time with a per-tick delay trace."""
    out = []
    for a, b in segs:
        a2 = max(0, a + _delay_at(trace, a, hop) + extra)
        b2 = min(limit, b + _delay_at(trace, max(a, b - 1), hop) + extra)
        if b2 > a2:
            out.append((int(a2), int(b2)))
    return out


def render_dynamic(engine, states, dry: np.ndarray, src_ids, rec_ids, fs: int, hop: int,
                   tail_policy: str):
    """Time-varying rendering (dynamic_v1, REQ-W06).

    The dry signal is split by Hann windows centred on every tick (hop = one
    tick); the windows sum to one, so a static scene reduces exactly to a
    single convolution.  A new RIR is computed only when the source or the
    receiver moved more than 5 cm since the last key tick; consecutive ticks
    sharing a key are convolved together.  Doppler is not modelled.
    """
    n_ticks = len(states)
    n_dry = dry.shape[1]
    win = np.zeros((n_ticks, n_dry))
    n = np.arange(n_dry)
    for t in range(n_ticks):
        x = (n - t * hop) / hop
        w = np.where(np.abs(x) < 1.0, 0.5 * (1.0 + np.cos(np.pi * x)), 0.0)
        win[t] = w
    win /= np.maximum(win.sum(axis=0), 1e-12)
    keys, delay_trace, first_rir, first_direct, doa_trace = {}, {}, {}, {}, {}
    for s in src_ids:
        for r in rec_ids:
            key_ticks, last = [], None
            delays, doas = np.zeros(n_ticks, dtype=np.int64), []
            for t, st in enumerate(states):
                sp = next(x.position for x in st.sources if x.source_id == s)
                rp = next(x.position for x in st.receivers if x.receiver_id == r)
                if last is None or np.linalg.norm(sp - last[0]) > RERENDER_THRESHOLD_M \
                        or np.linalg.norm(rp - last[1]) > RERENDER_THRESHOLD_M:
                    key_ticks.append(t)
                    last = (np.array(sp), np.array(rp))
                d = engine.compute_direct_path(st, s, r)
                delays[t] = int(d.delay_samples)
                doas.append([t * hop / fs, math.degrees(d.doa_az_rad), math.degrees(d.doa_el_rad), int(d.delay_samples)])
            keys[(s, r)] = key_ticks
            delay_trace[(s, r)] = delays
            doa_trace[(s, r)] = doas
    rir_cache = {}
    for (s, r), kt in keys.items():
        for t in kt:
            rir_cache[(s, r, t)] = engine.generate_rir(states[t], s, r)
        first_rir[(s, r)] = rir_cache[(s, r, kt[0])]
        first_direct[(s, r)] = engine.compute_direct_path(states[0], s, r)
    L_max = max(len(h.h) for h in rir_cache.values())
    T = n_dry + L_max - 1 if tail_policy == "keep" else n_dry
    refs = np.zeros((len(src_ids), len(rec_ids), T))
    for si, s in enumerate(src_ids):
        for ci, r in enumerate(rec_ids):
            kt = keys[(s, r)] + [n_ticks]
            for j in range(len(kt) - 1):
                w = win[kt[j]:kt[j + 1]].sum(axis=0)
                nz = np.flatnonzero(w > 0)
                if nz.size == 0:
                    continue
                a, b = int(nz[0]), int(nz[-1]) + 1
                seg = dry[si, a:b] * w[a:b]
                if not np.any(seg):
                    continue
                y = fftconvolve(seg, rir_cache[(s, r, kt[j])].h.astype(np.float64))
                e = min(T, a + len(y))
                refs[si, ci, a:e] += y[: e - a]
    info = {"n_ticks": n_ticks, "hop": hop,
            "key_rirs": {f"{s}->{r}": len(v) for (s, r), v in keys.items()}}
    return refs, first_rir, first_direct, delay_trace, doa_trace, info, T

# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def simulate_scene(
    config: SceneConfig,
    source_signals: Optional[Dict[str, np.ndarray]] = None,
) -> dict:
    """Render one static scene, QC it, and commit it atomically.

    Args:
        config: Validated SceneConfig.
        source_signals: Optional dry signals {source_id: float[N]} that take
            precedence over ``signal_path`` / synthetic signals.

    Returns:
        dict(scene_id, output_dir, manifest_path, acoustic_summary, elapsed_s,
             status="completed", fingerprint, audio_duration_s, bytes_written, qc)

    Raises:
        UnsupportedProfileError: config outside the static_v1 profile.
        SceneQCError: integrity check failed (output quarantined).
    """
    from simulator.if_modules.scene_world import SceneWorldBuilder
    from simulator.if_modules.propagation import AcousticPropagationEngine
    from simulator.if_modules.dynamics import DynamicSceneOrchestrator
    from simulator.if_modules.capture import CaptureDeviceChain
    from simulator.uf.w111_room_geometry import generate_bounding_volume

    t0 = time.time()
    raw = strip_private(scene_config_to_dict(config))
    resolved = resolve_config(raw)
    errors, approximations, profile_warnings = check_profile(resolved)
    if errors:
        raise UnsupportedProfileError("; ".join(errors))

    scene_id = config.scene_id
    out_root = config.output_dir
    fs = int(resolved["sample_rate"])
    duration_s = float(resolved["motion"]["duration_s"])
    n_dry = int(round(duration_s * fs))
    if n_dry < 1:
        raise ValueError("motion.duration_s must be positive.")

    # --- 1. dry sources and job identity --------------------------------
    dry, src_metas = prepare_sources(resolved, n_dry, source_signals)
    assets = asset_hashes(resolved)
    if source_signals:
        for m in src_metas:
            if m["kind"] == "array":
                assets[m["source_id"]] = None  # in-memory: not reproducible from config
    fingerprint = render_fingerprint(raw, assets=assets)

    # --- 2. array errors, scene build ------------------------------------
    eff, rec_records, arr_approx = apply_array_errors(resolved)
    approximations += arr_approx
    eff, rec_records = expand_binaural(eff, rec_records)
    rx_models = receiver_models(eff, fs)
    eff_cfg = SceneConfigValidator().validate(eff)
    eff_cfg.output_dir = out_root

    plaus_warnings: List[str] = list(profile_warnings)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        builder = SceneWorldBuilder(eff_cfg, seed=eff_cfg.seed)
        room = builder.build_room()
        materials = builder.build_materials()
        obstacles = builder.build_obstacles()
        plausibility = builder.validate()
        bbox = generate_bounding_volume(room)
        dyn = DynamicSceneOrchestrator(eff_cfg, bbox)
        src_traj, rec_traj = dyn.generate_trajectories()
        states = dyn.synchronize(src_traj, rec_traj, room, obstacles, materials)
    plaus_warnings += sorted({str(w.message) for w in caught})
    if not states:
        raise RuntimeError(f"[{scene_id}] No scene states generated")
    state = states[0]

    src_ids = [s["source_id"] for s in eff["sources"]]
    rec_ids = [r["receiver_id"] for r in eff["receivers"]]
    S, C = len(src_ids), len(rec_ids)
    ref_idx = rec_ids.index(eff.get("reference_receiver", rec_ids[0]))
    dynamic = resolved["render"]["profile"] == "dynamic_v1"
    tick_rate = float(resolved["motion"].get("tick_rate_hz", 50.0))
    hop = int(round(fs / tick_rate))
    if dynamic and abs(hop * tick_rate - fs) > 1e-6:
        raise UnsupportedProfileError(f"fs={fs} is not a multiple of tick_rate_hz={tick_rate}")

    # --- 3. propagation ---------------------------------------------------
    engine = AcousticPropagationEngine(
        fs=fs, c=float(resolved["speed_of_sound"]),
        ism_order=int(resolved["ism_order"]), seed=int(resolved["seed"]),
        fractional_delay=bool(resolved["render"].get("fractional_delay", False)),
        receiver_models=rx_models,
        band_reverb=bool(resolved["render"].get("band_reverb", False)),
    )
    from simulator.uf.w124_rir_rendering import FRACTIONAL_HALF_WIDTH
    kernel_hw = max(FRACTIONAL_HALF_WIDTH if engine.fractional_delay else 0,
                    BINAURAL_HALF_WIDTH if any(r.get("ear") for r in eff["receivers"]) else 0)
    dyn_info: Dict[str, object] = {}
    doa_trace: Dict = {}
    if dynamic:
        refs, rirs, directs, delay_trace, doa_trace, dyn_info, T = render_dynamic(
            engine, states, dry, src_ids, rec_ids, fs, hop, resolved["render"]["tail"])
    else:
        rirs, directs, delay_trace = {}, {}, {}
        for s in src_ids:
            for r in rec_ids:
                rirs[(s, r)] = engine.generate_rir(state, s, r)
                directs[(s, r)] = engine.compute_direct_path(state, s, r)
                delay_trace[(s, r)] = np.array([int(directs[(s, r)].delay_samples)])
        L_max = max(len(h.h) for h in rirs.values())
        T = n_dry + L_max - 1 if resolved["render"]["tail"] == "keep" else n_dry
        refs = np.zeros((S, C, T), dtype=np.float64)
        for si, s in enumerate(src_ids):
            for ci, r in enumerate(rec_ids):
                y = fftconvolve(dry[si], rirs[(s, r)].h.astype(np.float64), mode="full")
                n = min(len(y), T)
                refs[si, ci, :n] = y[:n]

    # --- 3b. roles, VAD and target SNR (REQ-202, REQ-204) -----------------
    roles = {s["source_id"]: s.get("role", "speech") for s in eff["sources"]}
    speech_idx = [i for i, s in enumerate(src_ids) if roles[s] == "speech"]
    noise_idx = [i for i, s in enumerate(src_ids) if roles[s] in ("noise", "interference")]
    dry_vad = {s: vad_segments(dry[i], fs) for i, s in enumerate(src_ids)}
    ref_trace = {s: delay_trace[(s, rec_ids[ref_idx])] for s in src_ids}
    speech_window = segments_to_mask(
        [seg for i in speech_idx
         for seg in shift_segments_varying(dry_vad[src_ids[i]], ref_trace[src_ids[i]], hop, T)], T)
    mix_meta: Dict[str, object] = {}
    target_snr = (resolved.get("mix") or {}).get("target_snr_db")
    if target_snr is not None and speech_idx and noise_idx and speech_window.any():
        sp = refs[speech_idx, ref_idx, :].sum(axis=0)[speech_window]
        nz = refs[noise_idx, ref_idx, :].sum(axis=0)[speech_window]
        p_s, p_n = float(np.mean(sp ** 2)), float(np.mean(nz ** 2))
        if p_n > 0 and p_s > 0:
            g = math.sqrt(p_s / (p_n * 10.0 ** (float(target_snr) / 10.0)))
            dry[noise_idx] *= g
            refs[noise_idx] *= g
            mix_meta["applied_noise_gain_db"] = 20.0 * math.log10(g)
        nz = refs[noise_idx, ref_idx, :].sum(axis=0)[speech_window]
        mix_meta["target_snr_db"] = float(target_snr)
        mix_meta["measured_snr_db"] = 10.0 * math.log10(p_s / max(float(np.mean(nz ** 2)), 1e-30))

    # Acoustic headroom: scale the whole scene (all sources, dry and images) so the
    # pre-device mixture peak stays below mix.max_peak_dbfs.  SNR and labels are
    # unchanged; device gain can still clip (that is device behaviour).
    max_peak = (resolved.get("mix") or {}).get("max_peak_dbfs")
    if max_peak is not None:
        peak = float(np.max(np.abs(refs.sum(axis=0))))
        limit = 10.0 ** (float(max_peak) / 20.0)
        if peak > limit:
            g_all = limit / peak
            dry *= g_all
            refs *= g_all
            mix_meta["applied_scene_gain_db"] = 20.0 * math.log10(g_all)
        mix_meta["max_peak_dbfs"] = float(max_peak)

    qc_checks: Dict[str, bool] = {}
    qc_details: Dict[str, object] = {}
    qc_flags: List[str] = []

    # QC: component sum against the independent float32 render path (static only;
    # the dynamic path has no independent renderer, which the manifest records)
    if dynamic:
        qc_details["component_sum"] = "not_applicable:dynamic_v1"
    else:
        indep = engine.render_scene(state, {s: dry[i].astype(np.float32) for i, s in enumerate(src_ids)})
        sum_err = 0.0
        for ci, r in enumerate(rec_ids):
            a = refs[:, ci, :].sum(axis=0)
            b = np.zeros(T)
            n = min(T, len(indep[r]))
            b[:n] = indep[r][:n]
            peak = max(float(np.max(np.abs(a))), 1e-12)
            sum_err = max(sum_err, float(np.max(np.abs(a - b))) / peak)
        qc_checks["component_sum"] = sum_err <= SUM_TOLERANCE_REL
        qc_details["component_sum_rel_err"] = sum_err

    # Clock shifts are a time transform on the channel: mixture and references move together.
    for ci, rec in enumerate(rec_records):
        refs[:, ci, :] = _shift(refs[:, ci, :], rec["clock_shift_samples"])
    mix_pre = refs.sum(axis=0)

    # --- 4. capture chain -------------------------------------------------
    chain = CaptureDeviceChain(eff_cfg, seed=eff_cfg.seed)
    mic_specs = [
        MicSpec(
            mic_id=r["receiver_id"],
            freq_response_db=np.zeros(0),       # flat: stage skipped (no added latency)
            freq_bins_hz=np.zeros(0),
            pattern_type="omni",
            sensitivity_db=float(r.get("sensitivity_db", 0.0)),
        )
        for r in eff["receivers"]
    ]
    mixture, chain_meta = chain.process_full_chain(mix_pre.astype(np.float32), mic_specs)
    noise = chain.last_noise_component
    noise_pre = chain.last_noise_pregain

    # --- 5. labels (reference channel) -----------------------------------
    pairs = []
    activity = {}
    for si, s in enumerate(src_ids):
        meta = src_metas[si]
        for ci, r in enumerate(rec_ids):
            d = directs[(s, r)]
            k = rec_records[ci]["clock_shift_samples"]
            tr = delay_trace[(s, r)]
            on = meta["onset_sample"]
            t_on = on // hop
            near = tr[max(0, t_on - 1): t_on + 2] if len(tr) > 1 else tr
            start = on + int(np.min(near)) + k
            end = on + meta["n_samples"] + _delay_at(tr, on + meta["n_samples"] - 1, hop) + k
            pairs.append({
                "source_id": s, "receiver_id": r,
                "distance_m": float(d.distance_m),
                "direct_delay_samples": int(d.delay_samples),
                "direct_delay_exact_samples": float(d.delay_s) * fs,
                "doa_az_deg": math.degrees(d.doa_az_rad),
                "doa_el_deg": math.degrees(d.doa_el_rad),
                "arrival_start": int(start), "arrival_end": int(end),
                "rt60_measured_s": float(rirs[(s, r)].rt60_measured_s),
                "drr_db": float(rirs[(s, r)].drr_db),
            })
            if ci == ref_idx:
                activity[s] = [int(max(0, start)), int(min(T, end))]
    mask = np.zeros((S, T), dtype=bool)
    for si, s in enumerate(src_ids):
        a, b = activity[s]
        mask[si, a:b] = True
    n_any = int(np.sum(mask.any(axis=0)))
    n_multi = int(np.sum(mask.sum(axis=0) >= 2))
    overlap_ratio = (n_multi / n_any) if n_any else 0.0
    vad_ref = {
        s: [list(seg) for seg in shift_segments_varying(
            dry_vad[s], ref_trace[s], hop, T, extra=rec_records[ref_idx]["clock_shift_samples"])]
        for s in src_ids
    }
    speaker_masks = [segments_to_mask(vad_ref[src_ids[i]], T) for i in speech_idx]
    overlap_ratio_vad = vad_overlap_ratio(speaker_masks)
    sens_ref = 10.0 ** (float(eff["receivers"][ref_idx].get("sensitivity_db", 0.0)) / 20.0)
    snr_db = {}
    for si, s in enumerate(src_ids):
        a, b = activity[s]
        ps = float(np.mean((sens_ref * refs[si, ref_idx, a:b]) ** 2)) if b > a else 0.0
        pn = float(np.mean(noise_pre[ref_idx, a:b].astype(np.float64) ** 2)) if b > a else 0.0
        snr_db[s] = (10.0 * math.log10(ps / pn)) if ps > 0 and pn > 0 else None

    # --- 6. remaining QC on arrays ---------------------------------------
    finite = all(np.all(np.isfinite(x)) for x in (dry, refs, mixture, noise)) and all(
        np.all(np.isfinite(h.h)) for h in rirs.values()
    )
    qc_checks["finite"] = bool(finite)

    causal_ok = True
    causal_bad = []
    for p in pairs:
        h = np.abs(rirs[(p["source_id"], p["receiver_id"])].h)
        first = int(np.argmax(h > 1e-3 * h.max())) if h.max() > 0 else -1
        si, ci = src_ids.index(p["source_id"]), rec_ids.index(p["receiver_id"])
        ref = refs[si, ci]
        peak = max(float(np.max(np.abs(ref))), 1e-30)
        pre = ref[: max(0, p["arrival_start"] - kernel_hw)]
        pre_ok = pre.size == 0 or float(np.max(np.abs(pre))) <= PRE_ARRIVAL_TOLERANCE_REL * peak
        if abs(first - p["direct_delay_samples"]) > 1 + kernel_hw or not pre_ok:
            causal_ok = False
            causal_bad.append(f"{p['source_id']}->{p['receiver_id']}")
    qc_checks["label_alignment"] = causal_ok
    if causal_bad:
        qc_details["label_alignment_failed_pairs"] = causal_bad

    unique_ok = True
    flat = [(src_ids[si], rec_ids[ci], refs[si, ci]) for si in range(S) for ci in range(C)]
    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            (s1, r1, a), (s2, r2, b) = flat[i], flat[j]
            if np.any(a) and np.array_equal(a, b):
                if s1 != s2:
                    unique_ok = False
                    qc_details.setdefault("identical_references", []).append([f"{s1}/{r1}", f"{s2}/{r2}"])
                else:
                    qc_flags.append(f"coincident_receivers:{r1},{r2}")
    qc_checks["unique_references"] = unique_ok

    clipped = chain_meta.get("clipped_samples", [0] * C)
    if sum(clipped) > 0:
        qc_flags.append("clipping")
    for ci, r in enumerate(eff["receivers"]):
        g = 10.0 ** (float(r.get("gain_db", 0.0)) / 20.0) * 10.0 ** (float(r.get("sensitivity_db", 0.0)) / 20.0)
        clip_level = 10.0 ** (float(r.get("clip_threshold_dbfs", 0.0)) / 20.0)
        if float(np.max(np.abs(mix_pre[ci]))) * g > clip_level:
            qc_flags.append(f"headroom:{r['receiver_id']}")
    if (resolved.get("impairments") or {}).get("allow_stress"):
        qc_flags.append("stress_condition")
    if resolved["qc"].get("fail_on_clip") and sum(clipped) > 0:
        qc_checks["no_clipping"] = False

    # --- 7. write to staging ---------------------------------------------
    staging = SceneStaging(out_root, scene_id)
    try:
        written: List[Tuple[str, np.ndarray, dict]] = []

        def _wav(name: str, data: np.ndarray, role: str, **ids):
            data32 = np.asarray(data, dtype=np.float32)
            staging.write_wav(name, data32, fs)
            written.append((name, data32, {"role": role, **ids}))

        full = resolved["render"].get("storage_profile", "full") == "full"
        for ci, r in enumerate(rec_ids):
            _wav(f"mixture__{r}.wav", mixture[ci], "mixture", receiver_id=r)
            if full:
                _wav(f"noise__{r}.wav", noise[ci], "noise", receiver_id=r)
        for si, s in enumerate(src_ids):
            if full:
                _wav(f"dry__{s}.wav", dry[si], "dry", source_id=s)
            for ci, r in enumerate(rec_ids):
                _wav(f"reference__{s}__{r}.wav", refs[si, ci], "reference", source_id=s, receiver_id=r)
                if full:
                    _wav(f"rir__{s}__{r}.wav", rirs[(s, r)].h, "rir", source_id=s, receiver_id=r)

        # QC: WAV round trip (format, shape, exact values)
        rt_ok = True
        for name, data32, _ in written:
            rfs, back = read_wav(staging.path(name))
            if rfs != fs or back.dtype != np.float32 or back.shape != data32.shape or not np.array_equal(back, data32):
                rt_ok = False
                qc_details.setdefault("wav_roundtrip_failed", []).append(name)
        qc_checks["wav_roundtrip"] = rt_ok

        first_pair = pairs[ref_idx]  # first source at the reference receiver
        acoustic_summary = AcousticSummary(
            scene_id=scene_id,
            rt60_measured_s=float(first_pair["rt60_measured_s"]),
            drr_db=float(first_pair["drr_db"]),
            snr_db=float(np.mean(chain_meta.get("snr_per_channel_db", [0.0]))),
            doa_az_deg=float(first_pair["doa_az_deg"]),
            doa_el_deg=float(first_pair["doa_el_deg"]),
            sabine_rt60_s=float(plausibility.predicted_rt60_s),
        )
        staging.write_json("params.json", resolved)
        staging.write_json("acoustic_summary.json", {
            "scene_id": scene_id,
            "rt60_measured_s": acoustic_summary.rt60_measured_s,
            "drr_db": acoustic_summary.drr_db,
            "snr_db": acoustic_summary.snr_db,
            "doa_az_deg": acoustic_summary.doa_az_deg,
            "doa_el_deg": acoustic_summary.doa_el_deg,
            "sabine_rt60_s": acoustic_summary.sabine_rt60_s,
        })

        files = []
        for name, data32, ids in written:
            p = staging.path(name)
            files.append({
                "path": staging.rel(name), **ids,
                "channels": 1, "n_samples": int(data32.shape[0]),
                "encoding": AUDIO_ENCODING,
                "sha256": sha256_file(p), "bytes": os.path.getsize(p),
            })
        for name, role in (("params.json", "params"), ("acoustic_summary.json", "summary")):
            p = staging.path(name)
            files.append({"path": staging.rel(name), "role": role, "encoding": "json",
                          "sha256": sha256_file(p), "bytes": os.path.getsize(p)})

        listed = {f["path"].split("/", 1)[1] for f in files} | {MANIFEST_NAME}
        on_disk = set(staging.staged_files()) | {MANIFEST_NAME}
        qc_checks["manifest_files"] = listed == on_disk

        qc_passed = all(qc_checks.values())
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION_V2,
            "scene_id": scene_id,
            "fingerprint": fingerprint,
            "renderer_version": RENDERER_VERSION,
            "created_at": now_iso(),
            "render": {
                "profile": resolved["render"]["profile"],
                "fs": fs, "n_samples": int(T), "n_dry": int(n_dry),
                "duration_s": duration_s, "tail_policy": resolved["render"]["tail"],
                "storage_profile": resolved["render"].get("storage_profile", "full"),
                "time_origin": "scene_start",
                "reference_receiver": rec_ids[ref_idx],
                "approximations": approximations,
                "validated_quantities": VALIDATED_QUANTITIES,
            },
            "sources": src_metas,
            "receivers": [
                {**rec, "device": {k: eff["receivers"][i].get(k) for k in (
                    "gain_db", "noise_floor_dbfs", "clip_threshold_dbfs", "sensitivity_db", "agc_enabled")}}
                for i, rec in enumerate(rec_records)
            ],
            "geometry": {"pairs": pairs, "n_obstacles": len(obstacles),
                         **({"dynamic": dyn_info} if dynamic else {})},
            "labels": {
                "reference_receiver": rec_ids[ref_idx],
                "activity": activity,
                "overlap_ratio": overlap_ratio,
                "snr_db": snr_db,
                "roles": roles,
                "vad": vad_ref,
                "overlap_ratio_vad": overlap_ratio_vad,
                **({"doa_trace": {s: doa_trace[(s, rec_ids[ref_idx])] for s in src_ids}} if dynamic else {}),
                "mix": mix_meta,
                "definitions": {
                    "vad": "1 ms frames of the dry stem with RMS > max frame RMS - 40 dB, shifted to the reference receiver",
                    "overlap_ratio_vad": "among speech sources: VAD samples with >=2 speakers / with >=1 speaker",
                    "mix": "target SNR = speech vs noise/interference references at the reference receiver over speech VAD (exact, pre-device)",
                    "activity": "placed dry segment shifted by direct delay (+clock shift) at the reference receiver",
                    "overlap_ratio": "samples with >=2 active sources / samples with >=1 active source",
                    "snr_db": "P(sensitivity*reference) / P(device self-noise, pre-gain) over the source's activity window",
                },
            },
            "device": {
                "snr_per_channel_db": chain_meta.get("snr_per_channel_db"),
                "clipped_samples": clipped,
                "nonlinear_applied": bool(chain_meta.get("nonlinear_applied", False)),
                "impairment": chain_meta.get("impairment"),
            },
            "plausibility": {
                "passed": bool(plausibility.passed),
                "errors": list(plausibility.errors),
                "warnings": plaus_warnings,
            },
            "files": files,
            "qc": {"passed": qc_passed, "checks": qc_checks, "flags": sorted(set(qc_flags)),
                   "details": qc_details},
            # v1 compatibility (paths relative to the output root)
            "source_count": S,
            "channel_count": C,
            "audio_files": [staging.rel(f"mixture__{r}.wav") for r in rec_ids],
            "rir_files": [staging.rel(f"rir__{s}__{r}.wav") for s in src_ids for r in rec_ids] if full else [],
            "metadata_json_path": staging.rel("params.json"),
            "acoustic_summary": {
                "RT60": acoustic_summary.rt60_measured_s,
                "DRR": acoustic_summary.drr_db,
                "SNR": acoustic_summary.snr_db,
                "DOA_az": acoustic_summary.doa_az_deg,
                "DOA_el": acoustic_summary.doa_el_deg,
            },
        }
        staging.write_json(MANIFEST_NAME, manifest)

        if not qc_passed:
            failed = [k for k, v in qc_checks.items() if not v]
            qdir = staging.quarantine(failed[0], f"QC failed: {failed}", {"checks": qc_checks, **qc_details})
            raise SceneQCError(failed[0], f"[{scene_id}] QC failed {failed}; quarantined at {qdir}",
                               {"checks": qc_checks, **qc_details})
        final_dir = staging.commit()
    except SceneQCError as exc:
        if not staging._closed:
            staging.quarantine(exc.check, str(exc), exc.details)
        raise
    except BaseException:
        staging.discard()
        raise

    bytes_written = sum(f["bytes"] for f in files) + os.path.getsize(os.path.join(final_dir, MANIFEST_NAME))
    return {
        "scene_id": scene_id,
        "output_dir": final_dir,
        "manifest_path": os.path.join(final_dir, MANIFEST_NAME),
        "acoustic_summary": acoustic_summary,
        "elapsed_s": time.time() - t0,
        "status": "completed",
        "fingerprint": fingerprint,
        "audio_duration_s": T / fs,
        "bytes_written": int(bytes_written),
        "qc": manifest["qc"],
    }
