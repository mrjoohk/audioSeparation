"""
File-based batch runner shared by the GUI ("Run from Files") and scripts.

Design: design_md/W100000/W1_audit_remediation_design.md §4.5–§4.6 (F-07, F-08).
The GUI previously ignored the worker count and reported "done" with the number
of *requested* scenes even when some failed.
"""
from __future__ import annotations

import os
from typing import List, Optional, Tuple

from simulator.config_resolver import load_raw_config, strip_private
from simulator.types import ExecutionSummary, SceneConfig
from simulator.uf.w151_config import SceneConfigValidator
from simulator.uf.w152_batch import run_batch

CHECKPOINT_NAME = "batch_checkpoint.json"


def load_config_files(
    paths: List[str], output_dir: Optional[str] = None
) -> Tuple[List[SceneConfig], List[Tuple[str, str]]]:
    """Load + validate JSON/YAML scene files.

    Returns:
        (configs, load_errors[(file_name, message)])
    """
    configs: List[SceneConfig] = []
    errors: List[Tuple[str, str]] = []
    seen = {}
    for path in paths:
        name = os.path.basename(path)
        try:
            raw = strip_private(load_raw_config(path))
            if output_dir:
                raw["output_dir"] = output_dir
            cfg = SceneConfigValidator().validate(raw)
            if cfg.scene_id in seen:
                raise ValueError(f"duplicate scene_id {cfg.scene_id!r} (also in {seen[cfg.scene_id]})")
            seen[cfg.scene_id] = name
            configs.append(cfg)
        except Exception as exc:  # pylint: disable=broad-except
            errors.append((name, f"{type(exc).__name__}: {exc}"))
    return configs, errors


def run_config_files(
    paths: List[str],
    output_dir: str,
    workers: int = 1,
    verify: str = "checksum",
) -> Tuple[ExecutionSummary, List[List[str]], List[Tuple[str, str]]]:
    """Validate and simulate scene files with checkpointed, verified resume.

    Returns:
        (summary, rows[[scene_id, status, detail]], load_errors)
    """
    from simulator.if_modules.orchestration import simulate_scene

    configs, load_errors = load_config_files(paths, output_dir)
    os.makedirs(output_dir, exist_ok=True)
    summary = run_batch(
        configs=configs,
        worker_count=max(1, int(workers)),
        output_dir=output_dir,
        simulate_fn=simulate_scene,
        checkpoint_file=os.path.join(output_dir, CHECKPOINT_NAME),
        verify=verify,
    )
    failed = set(summary.failed_scene_ids)
    rows: List[List[str]] = []
    for cfg in configs:
        sid = cfg.scene_id
        if sid in failed:
            rows.append([sid, "failed", summary.failure_reasons.get(sid, "")])
        else:
            rows.append([sid, "completed", ""])
    for name, msg in load_errors:
        rows.append([name, "load_error", msg[:200]])
    return summary, rows, load_errors


def summarize(summary: ExecutionSummary, n_load_errors: int = 0) -> str:
    """One-line status; never claims success when anything failed."""
    ok = summary.n_failed == 0 and n_load_errors == 0
    head = "Done" if ok else "Finished with failures"
    return (
        f"{head}: {summary.n_completed}/{summary.n_total} completed "
        f"({summary.n_skipped} reused), {summary.n_failed} failed, "
        f"{n_load_errors} file(s) not loaded; "
        f"{summary.audio_seconds_completed:.1f} s audio, {summary.bytes_written / 1e6:.1f} MB"
    )
