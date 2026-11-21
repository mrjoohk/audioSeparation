"""GUI callback logic (audit F-07), exercised without a browser.

``gradio`` is replaced by a stub so the callbacks in app.py can be called
directly; this also works where gradio's native dependencies cannot load.
"""
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from simulator.config_resolver import scene_signature
from simulator.scenarios.zoom_meeting import generate_zoom_scenario

ROOT = Path(__file__).parents[2]


@pytest.fixture
def app(monkeypatch):
    pytest.importorskip("plotly")
    fake = mock.MagicMock(name="gradio")
    fake.update = lambda **kw: kw
    monkeypatch.setitem(sys.modules, "gradio", fake)
    monkeypatch.syspath_prepend(str(ROOT))
    sys.modules.pop("app", None)
    mod = importlib.import_module("app")
    yield mod
    sys.modules.pop("app", None)


def _widget_values(updates):
    """The first 31 import outputs are the Scene Editor widget values, in order."""
    return [u["value"] for u in updates[:31]]


def _zoom_file(tmp_path, n=4):
    cfg = generate_zoom_scenario(n_participants=n, seed=3)
    cfg["receivers"][0]["gain_db"] = 6.0  # a field the editor cannot show
    p = tmp_path / "zoom.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg, SimpleNamespace(name=str(p))


def test_import_export_preserves_hidden_fields(app, tmp_path):
    cfg, f = _zoom_file(tmp_path)
    out = app.import_config(f)
    updates, msg, base = out[:31], out[31], out[32]
    assert updates[8]["value"] == 3                      # editor shows 3 of 4 sources
    assert "1 source(s) are kept unchanged" in msg
    assert base == cfg
    _, text = app.export_config(*_widget_values(updates), base)
    exported = json.loads(text)
    assert [s["source_id"] for s in exported["sources"]] == [s["source_id"] for s in cfg["sources"]]
    assert len(exported["room"]["obstacles"]) == len(cfg["room"]["obstacles"])
    assert exported["receivers"][0]["gain_db"] == 6.0
    assert scene_signature(exported) == scene_signature(cfg)


def test_yaml_import(app, tmp_path):
    yaml = pytest.importorskip("yaml")
    cfg = generate_zoom_scenario(n_participants=2, seed=1)
    p = tmp_path / "z.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = app.import_config(SimpleNamespace(name=str(p)))
    assert out[31].startswith("✅") and out[32] == cfg


def test_run_single_scene_uses_base_config(app, tmp_path):
    cfg, f = _zoom_file(tmp_path, n=2)
    cfg_short = dict(cfg, motion={"duration_s": 0.5}, ism_order=1)
    p = tmp_path / "short.json"
    p.write_text(json.dumps(cfg_short), encoding="utf-8")
    out = app.import_config(SimpleNamespace(name=str(p)))
    res = app.run_single_scene(*_widget_values(out[:31]), out[32])
    a0, status, rows = res[0], res[4], res[5]
    assert status.startswith("✅"), status
    assert "2 source(s)" in status
    assert a0 is not None and os.path.exists(a0)
    doa = dict(rows)["DOA Az (°)"]
    assert doa != "—"


def test_run_from_files_reports_failures(app, tmp_path):
    good = dict(generate_zoom_scenario(n_participants=2, seed=1), motion={"duration_s": 0.3}, ism_order=1)
    bad = dict(good, scene_id="bad_scene")
    bad["sources"] = good["sources"] + [dict(good["sources"][0])]   # duplicate id → load error
    files = []
    for name, c in (("good.json", good), ("bad.json", bad)):
        p = tmp_path / name
        p.write_text(json.dumps(c), encoding="utf-8")
        files.append(SimpleNamespace(name=str(p)))
    table, status = app.simulate_from_files(files, str(tmp_path / "out"), 1)
    assert status.startswith("⚠"), status
    statuses = {r[0]: r[1] for r in table}
    assert statuses[good["scene_id"]] == "completed"
    assert statuses["bad.json"] == "load_error"
