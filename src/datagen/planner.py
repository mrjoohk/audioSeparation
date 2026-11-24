"""
Scenario planner (REQ-201, REQ-203, REQ-206).

Turns a prior over rooms, arrays, speakers, noise, SNR and overlap tiers into
scene configs for the W1 renderer.  Sampling does no audio work, so 10,000
plans take seconds.  Overlap is scheduled on the speech assets' VAD (10 ms
frames) so that the rendered VAD-based overlap matches the tier target.

Leakage (REQ-206): speech/noise assets and room templates are assigned to
splits *before* synthesis; each split's plans draw only from its own pools.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from datagen.assets import Asset, AssetLibrary
from datatools.splits import assign_groups

FRAME_S = 0.01
OVERLAP_TOLERANCE = 0.05   # REQ-203: |overlap - target| < 5 %
ARRAYS = {
    "single": [[0.0, 0.0, 0.0]],
    "pair10": [[-0.05, 0.0, 0.0], [0.05, 0.0, 0.0]],
    "circular4": [[0.05, 0.0, 0.0], [0.0, 0.0, 0.05], [-0.05, 0.0, 0.0], [0.0, 0.0, -0.05]],
    # held-out geometries for robustness tests (REQ-303)
    "circular3_r3": [[0.03, 0.0, 0.0], [-0.015, 0.0, 0.026], [-0.015, 0.0, -0.026]],
    "linear3_4cm": [[-0.04, 0.0, 0.0], [0.0, 0.0, 0.0], [0.04, 0.0, 0.0]],
    "square4_8cm": [[0.04, 0.0, 0.04], [-0.04, 0.0, 0.04], [-0.04, 0.0, -0.04], [0.04, 0.0, -0.04]],
    # larger meeting-table arrays (spatial resolution below 1 kHz, REQ-401 benchmark)
    "circular4_r10": [[0.10, 0.0, 0.0], [0.0, 0.0, 0.10], [-0.10, 0.0, 0.0], [0.0, 0.0, -0.10]],
    "circular6_r10": [[round(0.10 * np.cos(a), 4), 0.0, round(0.10 * np.sin(a), 4)]
                      for a in np.arange(6) * np.pi / 3],
    # one binaural head (two ear channels); random yaw; measured HRTF subject drawn
    # from ScenarioPrior.hrtf_sofa when given (subject randomization), else synthetic
    "binaural": [[0.0, 0.0, 0.0]],
}


@dataclass
class ScenarioPrior:
    room_L: Tuple[float, float] = (3.0, 10.0)
    room_W: Tuple[float, float] = (3.0, 8.0)
    room_H: Tuple[float, float] = (2.5, 4.0)
    materials: Sequence[str] = ("wood", "carpet", "brick", "acoustic_tile", "concrete")
    n_speakers: Tuple[int, int] = (1, 4)
    arrays: Sequence[str] = ("single", "pair10", "circular4")
    tiers: Mapping[str, float] = field(default_factory=lambda: {"easy": 0.0, "medium": 0.2, "hard": 0.5})
    tier_weights: Mapping[str, float] = field(default_factory=lambda: {"easy": 1, "medium": 1, "hard": 1})
    snr_db: Tuple[float, float] = (0.0, 20.0)
    noise_prob: float = 0.8
    event_prob: float = 0.3              # REQ-203: transient interference events
    event_level_db: Tuple[float, float] = (-30.0, -15.0)
    duration_s: float = 6.0
    speech_level_dbfs: Tuple[float, float] = (-30.0, -22.0)
    sample_rate: int = 16000
    ism_order: int = 3
    n_room_templates: int = 60
    storage_profile: str = "training"
    max_peak_dbfs: float = -1.0          # acoustic headroom applied by the renderer
    fractional_delay_arrays: bool = True # multi-mic arrays need sub-sample delays (REQ-W03, §11)
    calibration: Optional[Mapping] = None  # W3 calibration profile (REQ-302, design §6.3)
    hrtf_sofa: Sequence[str] = ()          # measured HRTF subjects (SOFA files) for "binaural"
    max_duration_s: Optional[float] = None   # scene may grow up to this to reach a tier (default 1.5x)

    @classmethod
    def from_dict(cls, d: Mapping) -> "ScenarioPrior":
        kw = {}
        for k, v in d.items():
            if k not in cls.__dataclass_fields__:
                raise ValueError(f"unknown prior key {k!r}")
            kw[k] = tuple(v) if isinstance(v, list) else v
        return cls(**kw)


# ---------------------------------------------------------------------------
# Splits of source assets and room templates (before synthesis)
# ---------------------------------------------------------------------------

def make_room_catalog(prior: ScenarioPrior, seed: int = 0) -> List[dict]:
    rng = np.random.default_rng(seed)
    out = []
    for i in range(prior.n_room_templates):
        out.append({
            "room_id": f"room{i:04d}",
            "dims": {"L": round(float(rng.uniform(*prior.room_L)), 2),
                     "W": round(float(rng.uniform(*prior.room_W)), 2),
                     "H": round(float(rng.uniform(*prior.room_H)), 2)},
            "material": str(rng.choice(list(prior.materials))),
        })
    return out


def split_pools(lib: AssetLibrary, rooms: List[dict], ratios: Mapping[str, float],
                seed: int = 0) -> Dict[str, Dict[str, List[str]]]:
    """{split: {"speech": [...], "noise": [...], "rooms": [...]}} with no shared keys."""
    # Speech, noise and rooms are split independently so each split gets its share of each.
    items = lib.split_items()
    kinds = {a.asset_id: a.kind for a in lib.assets.values()}
    a_split = {}
    for kind, keys in (("speech", ("speaker", "recording")), ("noise", ("noise",)), ("event", ("event",))):
        sub = [it for it in items if kinds[it["id"]] == kind]
        if sub:
            a_split.update(assign_groups(sub, ratios, group_keys=keys, seed=seed))
    r_split = assign_groups([{"id": r["room_id"], "keys": {"room": r["room_id"]}} for r in rooms],
                            ratios, group_keys=("room",), seed=seed + 1)
    pools = {s: {"speech": [], "noise": [], "event": [], "rooms": []} for s in ratios}
    for aid, sp in a_split.items():
        pools[sp][lib.assets[aid].kind].append(aid)
    for rid, sp in r_split.items():
        pools[sp]["rooms"].append(rid)
    for sp, p in pools.items():
        for k in p:
            p[k].sort()
    return pools


# ---------------------------------------------------------------------------
# Overlap scheduling on VAD (REQ-203)
# ---------------------------------------------------------------------------

def _frames(asset: Asset, n_frames: int) -> np.ndarray:
    hop = asset.fs * FRAME_S
    m = np.zeros(n_frames, dtype=np.float64)
    for s, e in asset.vad:
        a, b = int(round(s / hop)), int(round(e / hop))   # nearest frame: unbiased vs 1 ms VAD
        m[a:min(b, n_frames)] = 1.0
    return m


def schedule_onsets(masks: Sequence[np.ndarray], total_frames: int, target: float,
                    rng: np.random.Generator,
                    running: Tuple[float, float] = (0.0, 0.0)) -> Tuple[List[int], float]:
    """Choose an onset (frames) per utterance so the overlap ratio approaches ``target``.

    Utterance 0 starts within the first 0.5 s; each next one is placed at the
    onset (keeping it inside the scene) whose resulting overlap ratio is closest
    to the target (ties broken randomly).  For the last utterance the error is
    measured on the *cumulative* ratio including ``running`` = (any, multi)
    frame totals of earlier scenes in the same tier, which is what REQ-203
    checks.  Returns (onsets, achieved_ratio of this scene).
    """
    cnt = np.zeros(total_frames)
    onsets: List[int] = []
    for k, m in enumerate(masks):
        L = min(len(m), total_frames)
        m = m[:L]
        if k == 0:
            o = int(rng.integers(0, max(1, min(50, total_frames - L + 1))))
        else:
            any_ = (cnt >= 1).astype(float)
            single = (cnt == 1).astype(float)
            n_any, n_multi = any_.sum(), (cnt >= 2).sum()
            max_o = total_frames - L
            if max_o < 0:
                max_o = 0
            # overlap counts for every onset o in [0, max_o] (direct correlation;
            # cheaper than FFT for 10 ms frame masks of a few hundred frames)
            ov_any = np.correlate(any_, m, mode="valid")[: max_o + 1]
            ov_single = np.correlate(single, m, mode="valid")[: max_o + 1]
            new_any = n_any + m.sum() - np.rint(ov_any)
            new_multi = n_multi + np.rint(ov_single)
            if k == len(masks) - 1:
                ratio = (running[1] + new_multi) / np.maximum(running[0] + new_any, 1)
            else:
                ratio = np.where(new_any > 0, new_multi / np.maximum(new_any, 1), 0.0)
            err = np.abs(ratio - target)
            best = np.flatnonzero(err <= err.min() + 0.01)
            o = int(rng.choice(best))
        cnt[o:o + L] += m
        onsets.append(o)
    n_any = (cnt >= 1).sum()
    return onsets, float((cnt >= 2).sum() / n_any) if n_any else 0.0


def _counts(masks, onsets, total_frames) -> Tuple[float, float]:
    cnt = np.zeros(total_frames)
    for m, o in zip(masks, onsets):
        L = min(len(m), total_frames - o)
        cnt[o:o + L] += m[:L]
    return float((cnt >= 1).sum()), float((cnt >= 2).sum())


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def _plan_hash(cfg: Mapping) -> str:
    body = {k: v for k, v in cfg.items() if k not in ("scene_id", "output_dir")}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _point(rng, dims, margin=0.5, y=(1.1, 1.7)):
    return [round(float(rng.uniform(margin, dims["L"] - margin)), 3),
            round(float(rng.uniform(*y)), 3),
            round(float(rng.uniform(margin, dims["W"] - margin)), 3)]


def sample_scenarios(
    prior: ScenarioPrior,
    n: int,
    lib: AssetLibrary,
    pools: Mapping[str, Mapping[str, List[str]]],
    rooms: Sequence[dict],
    split: str,
    seed: int = 0,
    output_dir: str = "output",
    tier: Optional[str] = None,
) -> List[dict]:
    """Return ``n`` plans: {"config": scene dict, "plan": metadata}."""
    rng = np.random.default_rng(seed)
    pool = pools[split]
    room_by_id = {r["room_id"]: r for r in rooms}
    speakers: Dict[str, List[str]] = {}
    for aid in pool["speech"]:
        speakers.setdefault(lib.assets[aid].keys["speaker"], []).append(aid)
    spk_ids = sorted(speakers)
    if not spk_ids or not pool["rooms"]:
        raise ValueError(f"split {split!r} has no speakers or rooms")
    tiers = list(prior.tiers)
    tw = np.array([prior.tier_weights.get(t, 1.0) for t in tiers], float)
    tw /= tw.sum()
    fs = prior.sample_rate
    total_frames = int(round(prior.duration_s / FRAME_S))
    mask_cache: Dict[str, np.ndarray] = {}
    running: Dict[str, Tuple[float, float]] = {t: (0.0, 0.0) for t in tiers}
    # calibration targets: "random" draws with replacement; "stratified" renders each
    # target once (cycled through a seeded permutation) so a regenerated set reproduces
    # the target distribution without bootstrap noise (closed-loop REQ-302).
    cal = prior.calibration or {}
    cal_order = (np.random.default_rng([seed, 0x52543630]).permutation(len(cal["rt60_samples"]))
                 if cal.get("assignment") == "stratified" else None)
    plans = []
    for i in range(n):
        t = tier or tiers[int(rng.choice(len(tiers), p=tw))]
        target = float(prior.tiers[t])
        lo, hi = prior.n_speakers
        if target > 0:
            lo = max(lo, 2)
        # Tier-aware starting speaker count (fewer scheduling retries): more
        # overlap needs more simultaneous talkers.
        k_hi = min(hi, len(spk_ids))
        k0 = lo + int(round(target * 4))
        k = int(np.clip(rng.integers(k0, k0 + 2), lo, k_hi))
        chosen = [spk_ids[j] for j in rng.choice(len(spk_ids), size=k, replace=False)]
        utts = [speakers[s][int(rng.integers(len(speakers[s])))] for s in chosen]
        masks = []
        for u in utts:
            if u not in mask_cache:
                n_fr = int(np.ceil(lib.assets[u].n_samples / (lib.assets[u].fs * FRAME_S)))
                mask_cache[u] = _frames(lib.assets[u], n_fr)
            masks.append(mask_cache[u])
        onsets, achieved = schedule_onsets(masks, total_frames, target, rng, running[t])
        # Too many speakers for the scene length can force overlap above the tier
        # target: drop speakers until the target is reachable (or the minimum).
        while abs(achieved - target) > OVERLAP_TOLERANCE and k > lo:
            k -= 1
            chosen, utts, masks = chosen[:k], utts[:k], masks[:k]
            onsets, achieved = schedule_onsets(masks, total_frames, target, rng, running[t])
        # Below target (cumulative): add speakers while the prior allows.
        k_max = min(hi, len(spk_ids))
        while target - achieved > OVERLAP_TOLERANCE and k < k_max:
            extra = [x for x in spk_ids if x not in chosen]
            new = extra[int(rng.integers(len(extra)))]
            u = speakers[new][int(rng.integers(len(speakers[new])))]
            if u not in mask_cache:
                n_fr = int(np.ceil(lib.assets[u].n_samples / (lib.assets[u].fs * FRAME_S)))
                mask_cache[u] = _frames(lib.assets[u], n_fr)
            chosen, utts, masks = chosen + [new], utts + [u], masks + [mask_cache[u]]
            k += 1
            onsets, achieved = schedule_onsets(masks, total_frames, target, rng, running[t])
        # Still forced above target with the fewest speakers: lengthen the scene.
        scene_frames = total_frames
        max_frames = int(round((prior.max_duration_s or 1.5 * prior.duration_s) / FRAME_S))
        while achieved - target > OVERLAP_TOLERANCE and scene_frames < max_frames:
            scene_frames = min(max_frames, int(scene_frames * 1.1) + 1)
            onsets, achieved = schedule_onsets(masks, scene_frames, target, rng, running[t])
        a_, m_ = _counts(masks, onsets, scene_frames)
        running[t] = (running[t][0] + a_, running[t][1] + m_)

        room = room_by_id[pool["rooms"][int(rng.integers(len(pool["rooms"])))]]
        dims = room["dims"]
        arr = str(rng.choice(list(prior.arrays)))
        center = [round(float(rng.uniform(1.0, dims["L"] - 1.0)), 3),
                  round(float(rng.uniform(0.75, 1.2)), 3),
                  round(float(rng.uniform(1.0, dims["W"] - 1.0)), 3)]
        receivers = [{"receiver_id": f"m{j}", "position": [round(center[0] + d[0], 4), center[1], round(center[2] + d[2], 4)]}
                     for j, d in enumerate(ARRAYS[arr])]
        if arr == "binaural":
            receivers = [{"receiver_id": "head", "position": list(center), "binaural": True,
                          "yaw_deg": round(float(rng.uniform(-180.0, 180.0)), 1)}]
            if prior.hrtf_sofa:
                receivers[0]["hrtf"] = {"sofa": str(prior.hrtf_sofa[int(rng.integers(len(prior.hrtf_sofa)))])}
        sources = []
        for j, (spk, u, o) in enumerate(zip(chosen, utts, onsets)):
            for _ in range(50):
                p = _point(rng, dims)
                if np.linalg.norm(np.subtract(p, center)) > 0.6:
                    break
            sources.append({
                "source_id": f"spk{j}", "role": "speech", "position": p,
                "signal_path": lib.abspath(lib.assets[u]), "onset_s": round(o * FRAME_S, 3),
                "level_dbfs": round(float(rng.uniform(*prior.speech_level_dbfs)), 2),
            })
        noise_id = None
        snr = None
        if pool["noise"] and rng.random() < prior.noise_prob:
            noise_id = pool["noise"][int(rng.integers(len(pool["noise"])))]
            snr = round(float(rng.uniform(*prior.snr_db)), 2)
            sources.append({
                "source_id": "noise0", "role": "noise",
                "position": [round(float(rng.uniform(0.3, dims["L"] - 0.3)), 3),
                             round(float(rng.uniform(0.3, dims["H"] - 0.3)), 3), 0.3],
                "signal_path": lib.abspath(lib.assets[noise_id]),
            })
        event_ids = []
        if pool.get("event") and rng.random() < prior.event_prob:
            for e in range(int(rng.integers(1, 3))):
                eid = pool["event"][int(rng.integers(len(pool["event"])))]
                ev = lib.assets[eid]
                ev_len = ev.n_samples / ev.fs
                event_ids.append(eid)
                sources.append({
                    "source_id": f"event{e}", "role": "interference",
                    "position": _point(rng, dims, y=(0.4, 1.2)),
                    "signal_path": lib.abspath(ev),
                    "onset_s": round(float(rng.uniform(0, max(0.0, scene_frames * FRAME_S - ev_len))), 3),
                    "level_dbfs": round(float(rng.uniform(*prior.event_level_db)), 2),
                })
        materials = {"default": room["material"]}
        target_rt60 = None
        if prior.calibration:
            from training.calibration import alpha_for_rt60
            samples = prior.calibration["rt60_samples"]
            if cal_order is not None:
                target_rt60 = float(samples[cal_order[i % len(samples)]])
            else:
                target_rt60 = float(rng.choice(samples))
            a = round(alpha_for_rt60(dims, target_rt60), 4)
            materials = {"default": {"alpha": [a] * 6}}
        cfg = {
            "scene_id": f"{split}_{i:06d}",
            "seed": int(rng.integers(1 << 31)),
            "room": {"type": "shoebox", "dimensions": dict(dims)},
            "materials": materials,
            "sources": sources,
            "receivers": receivers,
            "motion": {"duration_s": round(scene_frames * FRAME_S, 3)},
            "sample_rate": fs,
            "ism_order": prior.ism_order,
            "render": {"storage_profile": prior.storage_profile,
                       "fractional_delay": bool(prior.fractional_delay_arrays and len(receivers) > 1)},
            "output_dir": output_dir,
        }
        cfg["mix"] = {"max_peak_dbfs": prior.max_peak_dbfs}
        if snr is not None:
            cfg["mix"]["target_snr_db"] = snr
        plan = {
            "split": split, "tier": t, "target_overlap": target, "planned_overlap": achieved,
            "planned_any_frames": a_, "planned_multi_frames": m_,
            "room_id": room["room_id"], "array": arr, "speakers": chosen, "utterances": utts,
            "noise_id": noise_id, "event_ids": event_ids, "target_snr_db": snr, "n_speakers": k,
            "target_rt60_s": target_rt60,
            "calibration_profile": (prior.calibration or {}).get("id"),
        }
        plan["hash"] = _plan_hash(cfg)
        plans.append({"config": cfg, "plan": plan})
    return plans


def check_plan_constraints(plans: Sequence[dict], prior: ScenarioPrior) -> List[str]:
    """Return constraint violations (REQ-201 acceptance)."""
    bad = []
    for p in plans:
        c, m = p["config"], p["plan"]
        d = c["room"]["dimensions"]
        if not (prior.room_L[0] <= d["L"] <= prior.room_L[1]):
            bad.append(f"{c['scene_id']}: L={d['L']}")
        if not (prior.n_speakers[0] <= m["n_speakers"] <= prior.n_speakers[1]):
            bad.append(f"{c['scene_id']}: speakers={m['n_speakers']}")
    return bad


def duplicate_rate(plans: Sequence[dict]) -> float:
    hashes = [p["plan"]["hash"] for p in plans]
    return 1.0 - len(set(hashes)) / len(hashes) if hashes else 0.0
