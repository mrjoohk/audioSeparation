"""config_resolver: one interpreter for API and GUI (audit F-07, F-09)."""
import json

import pytest

from simulator.config_resolver import (
    apply_editor_overrides,
    check_profile,
    editor_view,
    load_raw_config,
    preflight,
    render_fingerprint,
    resolve_config,
    scene_signature,
)
from simulator.scenarios.zoom_meeting import generate_zoom_scenario

MAX_S, MAX_R = 3, 4


def _edits_from_view(v, n_sources, n_receivers):
    pad = lambda lst, n: [p if p is not None else [1.0, 1.0, 1.0] for p in lst] + [[1.0, 1.0, 1.0]] * (n - len(lst))
    return {
        "scene_id": v["scene_id"], "seed": v["seed"], "room_dims": v["room_dims"],
        "material": v["material"], "ism_order": v["ism_order"], "sample_rate": v["sample_rate"],
        "n_sources": n_sources, "source_positions": pad(v["source_positions"], MAX_S),
        "n_receivers": n_receivers, "receiver_positions": pad(v["receiver_positions"], MAX_R),
    }


def test_zoom_roundtrip_signature(tmp_path):
    """4-person Zoom JSON → editor (no edits) → export keeps the scene signature,
    all 4 sources, all obstacles and the original IDs (audit: 4→3, 6→0, person_0→s0)."""
    zoom = generate_zoom_scenario(n_participants=4, seed=3)
    p = tmp_path / "zoom.json"
    p.write_text(json.dumps(zoom), encoding="utf-8")
    base = load_raw_config(str(p))
    v = editor_view(base, MAX_S, MAX_R)
    assert v["n_sources_hidden"] == 1 and v["n_obstacles"] == len(zoom["room"]["obstacles"])
    merged = apply_editor_overrides(
        base, _edits_from_view(v, min(4, MAX_S), min(1, MAX_R)), MAX_S, MAX_R
    )
    assert [s["source_id"] for s in merged["sources"]] == [s["source_id"] for s in zoom["sources"]]
    assert len(merged["room"]["obstacles"]) == len(zoom["room"]["obstacles"])
    assert merged["_zoom_meta"] == zoom["_zoom_meta"]
    assert scene_signature(merged) == scene_signature(zoom)


def test_editor_change_is_applied_and_changes_signature():
    zoom = generate_zoom_scenario(n_participants=2, seed=1)
    v = editor_view(zoom, MAX_S, MAX_R)
    e = _edits_from_view(v, 2, 1)
    e["source_positions"][0] = [1.0, 1.2, 1.0]
    merged = apply_editor_overrides(zoom, e, MAX_S, MAX_R)
    assert merged["sources"][0]["position"] == [1.0, 1.2, 1.0]
    assert merged["sources"][0]["source_id"] == "person_0"
    assert scene_signature(merged) != scene_signature(zoom)


def test_editor_adds_unique_ids():
    base = {"scene_id": "x", "seed": 1, "room": {"type": "shoebox", "dimensions": {"L": 5, "W": 4, "H": 3}},
            "sources": [{"source_id": "s1", "position": [1, 1, 1]}],
            "receivers": [{"receiver_id": "r0", "position": [2, 1, 2]}]}
    e = {"n_sources": 3, "source_positions": [[1, 1, 1], [2, 1, 1], [3, 1, 1]],
         "n_receivers": 1, "receiver_positions": [[2, 1, 2]] * 4}
    merged = apply_editor_overrides(base, e, MAX_S, MAX_R)
    ids = [s["source_id"] for s in merged["sources"]]
    assert ids[0] == "s1" and len(set(ids)) == 3


def test_yaml_import(tmp_path):
    yaml = pytest.importorskip("yaml")
    cfg = generate_zoom_scenario(n_participants=2, seed=5)
    p = tmp_path / "z.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    assert scene_signature(load_raw_config(str(p))) == scene_signature(cfg)


def test_fingerprint_ignores_display_fields_and_defaults():
    a = {"scene_id": "a", "seed": 1, "output_dir": "x",
         "room": {"type": "shoebox", "dimensions": {"L": 5, "W": 4, "H": 3}},
         "sources": [{"source_id": "s0", "position": {"x": 1, "y": 1, "z": 1}}],
         "receivers": [{"receiver_id": "r0", "position": [2, 1, 2]}]}
    b = json.loads(json.dumps(a))
    b.update(scene_id="b", output_dir="y", sample_rate=16000, ism_order=3)
    b["sources"][0]["position"] = [1.0, 1.0, 1.0]
    b["receivers"][0]["gain_db"] = 0.0
    assert render_fingerprint(a) == render_fingerprint(b)
    b["seed"] = 2
    assert render_fingerprint(a) != render_fingerprint(b)


def test_profile_rejects_directivity_and_motion():
    cfg = resolve_config({
        "scene_id": "p", "seed": 0,
        "room": {"type": "shoebox", "dimensions": {"L": 5, "W": 4, "H": 3}},
        "sources": [{"source_id": "s0", "motion": {"type": "random_walk"}}],
        "receivers": [{"receiver_id": "r0", "position": [2, 1, 2], "pattern": "cardioid"}],
    })
    errors, approx, _ = check_profile(cfg)
    assert any("moving" in e for e in errors)
    assert any("cardioid" in e for e in errors)


def test_preflight_reports_workload_and_errors():
    good = generate_zoom_scenario(n_participants=2, seed=0)
    pf = preflight(good)
    assert pf["ok"], pf["errors"]
    w = pf["workload"]
    assert w["n_pairs"] == 2 and w["estimated_bytes"] > 0 and pf["signature"]
    bad = dict(good, sources=good["sources"] + [dict(good["sources"][0])])  # duplicate id
    pf2 = preflight(bad)
    assert not pf2["ok"] and any("Duplicate" in e for e in pf2["errors"])
