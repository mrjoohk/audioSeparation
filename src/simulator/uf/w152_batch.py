"""
UF-W152: Batch Execution, Job Queue, and Resource Tracking.

Implements UF-W152-01 through UF-W152-04:
  - JobQueue:      iterable job queue with checkpoint resume support
  - BatchExecutor: multiprocessing pool executor with per-job error handling
  - track_resource_usage: psutil-based memory/CPU monitor
  - run_batch:     top-level convenience function
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_SRC = _HERE.parent.parent.parent  # .../src/
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from simulator.types import ExecutionSummary, SceneConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JobQueue
# ---------------------------------------------------------------------------


class JobQueue:
    """Job queue with fingerprint-aware, output-verified checkpoint resume.

    A job is skipped only when (design §4.5, F-08):
      1. the checkpoint records it as ``completed`` with the same fingerprint, and
      2. its committed output verifies (manifest fingerprint + file checksums).

    Checkpoint v2 format::

        {"schema": 2, "jobs": {scene_id: {"fingerprint", "status", "reason", "updated_at"}}}

    A v1 checkpoint (JSON list of completed scene_ids) is accepted, but because it
    carries no fingerprint a listed job is reused only if its output verifies
    against the job's *current* fingerprint.

    Args:
        verify: "checksum" (default), "exists" (manifest + file sizes) or
            "none" (trust the checkpoint fingerprint; for simulate_fns that do
            not write v2 manifests).

    Usage::

        queue = JobQueue(configs, checkpoint_file="ckpt.json")
        for cfg in queue:
            result = simulate(cfg)
            queue.mark_complete(cfg.scene_id)
    """

    CHECKPOINT_SCHEMA = 2

    def __init__(
        self,
        configs: List[SceneConfig],
        checkpoint_file: Optional[str] = None,
        verify: str = "checksum",
    ) -> None:
        if verify not in ("checksum", "exists", "none"):
            raise ValueError(f"verify must be checksum|exists|none, got {verify!r}")
        self._configs: List[SceneConfig] = list(configs)
        self._checkpoint_file: Optional[str] = checkpoint_file
        self._verify = verify
        self._jobs: Dict[str, dict] = {}
        self._legacy_ids: set = set()
        self._fingerprints: Dict[str, str] = {}
        self._skip: Optional[Dict[str, str]] = None   # scene_id -> reason for decision
        self.decisions: Dict[str, str] = {}

        if checkpoint_file:
            self.load_checkpoint()

    # ------------------------------------------------------------------
    @property
    def _completed_ids(self) -> set:
        """IDs recorded as completed (v2) or listed in a v1 checkpoint."""
        done = {sid for sid, j in self._jobs.items() if j.get("status") == "completed"}
        return done | self._legacy_ids

    def fingerprint(self, cfg: SceneConfig) -> str:
        if cfg.scene_id not in self._fingerprints:
            from simulator.config_resolver import render_fingerprint
            from simulator.uf.w151_config import scene_config_to_dict
            self._fingerprints[cfg.scene_id] = render_fingerprint(scene_config_to_dict(cfg))
        return self._fingerprints[cfg.scene_id]

    # ------------------------------------------------------------------
    def load_checkpoint(self) -> None:
        if not self._checkpoint_file:
            return
        p = Path(self._checkpoint_file)
        if not p.exists():
            logger.debug("No checkpoint file found at %s — starting fresh.", p)
            return
        try:
            with p.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to load checkpoint: %s", exc)
            return
        if isinstance(data, list):
            self._legacy_ids.update(str(x) for x in data)
            logger.info("Legacy checkpoint: %d id(s); outputs will be verified.", len(data))
        elif isinstance(data, dict) and data.get("schema") == self.CHECKPOINT_SCHEMA:
            self._jobs.update(data.get("jobs", {}))
        else:
            logger.warning("Checkpoint file has unexpected format; ignoring.")

    def _write_checkpoint(self) -> None:
        if not self._checkpoint_file:
            return
        p = Path(self._checkpoint_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump({"schema": self.CHECKPOINT_SCHEMA, "jobs": self._jobs}, fh,
                          indent=2, sort_keys=True)
            os.replace(tmp, p)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to save checkpoint: %s", exc)

    def save_checkpoint(self, completed_ids: List[str]) -> None:
        """Record *completed_ids* as completed (kept for API compatibility)."""
        by_id = {c.scene_id: c for c in self._configs}
        for sid in completed_ids:
            entry = self._jobs.setdefault(sid, {})
            entry["status"] = "completed"
            if sid in by_id:
                entry["fingerprint"] = self.fingerprint(by_id[sid])
            entry["updated_at"] = _now()
        self._write_checkpoint()

    # ------------------------------------------------------------------
    def mark_complete(self, scene_id: str) -> None:
        self._set_status(scene_id, "completed", "")

    def mark_failed(self, scene_id: str, reason: str) -> None:
        self._set_status(scene_id, "failed", reason)

    def _set_status(self, scene_id: str, status: str, reason: str) -> None:
        by_id = {c.scene_id: c for c in self._configs}
        fp = self.fingerprint(by_id[scene_id]) if scene_id in by_id else None
        self._jobs[scene_id] = {"fingerprint": fp, "status": status, "reason": reason,
                                "updated_at": _now()}
        if self._skip is not None:
            self._skip.pop(scene_id, None)
        self._write_checkpoint()

    # ------------------------------------------------------------------
    def _decide(self) -> Dict[str, str]:
        """Compute which jobs are already done (verified)."""
        from simulator.scene_io import verify_scene_output
        skip: Dict[str, str] = {}
        for cfg in self._configs:
            sid = cfg.scene_id
            job = self._jobs.get(sid)
            fp = self.fingerprint(cfg)
            if job is not None:
                if job.get("status") != "completed":
                    self.decisions[sid] = f"rerun:previous_{job.get('status')}"
                    continue
                if job.get("fingerprint") != fp:
                    self.decisions[sid] = "rerun:fingerprint_changed"
                    continue
            elif sid not in self._legacy_ids:
                self.decisions[sid] = "run:new"
                continue
            if self._verify == "none" and job is not None:
                skip[sid] = "checkpoint"
                self.decisions[sid] = "skip:checkpoint"
                continue
            ok, why = verify_scene_output(
                cfg.output_dir, sid, expected_fingerprint=fp,
                mode="checksum" if self._verify == "checksum" else "exists",
            )
            if ok:
                skip[sid] = "verified"
                self.decisions[sid] = "skip:verified"
            else:
                self.decisions[sid] = f"rerun:{why}"
        return skip

    @property
    def pending_count(self) -> int:
        """Number of configs that will be (re)run."""
        return sum(1 for _ in self)

    def __iter__(self):
        """Yield pending SceneConfig objects (skip verified completed jobs)."""
        if self._skip is None:
            self._skip = self._decide()
        for cfg in self._configs:
            if cfg.scene_id not in self._skip:
                yield cfg

    @property
    def skipped_ids(self) -> List[str]:
        if self._skip is None:
            self._skip = self._decide()
        return sorted(self._skip)

    def duplicate_groups(self) -> List[List[str]]:
        """Scene IDs that share a render fingerprint (same job under different IDs)."""
        groups: Dict[str, List[str]] = {}
        for cfg in self._configs:
            groups.setdefault(self.fingerprint(cfg), []).append(cfg.scene_id)
        return [sorted(v) for v in groups.values() if len(v) > 1]

    def __len__(self) -> int:
        return len(self._configs)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def classify_failure(exc: BaseException) -> str:
    """Map an exception to a checkpoint/summary reason string."""
    from simulator.scene_io import SceneQCError, UnsupportedProfileError
    from simulator.uf.w151_config import ValidationError
    if isinstance(exc, SceneQCError):
        return f"qc:{exc.check}"
    if isinstance(exc, UnsupportedProfileError):
        return "unsupported_profile"
    if isinstance(exc, ValidationError):
        return "validation"
    return f"error:{type(exc).__name__}"


# ---------------------------------------------------------------------------
# Resource tracking
# ---------------------------------------------------------------------------


def track_resource_usage(pid: Optional[int] = None) -> dict:
    """Return memory and CPU usage for the given PID (default: current process).

    Requires *psutil* (``pip install psutil``).  If psutil is not available,
    returns an empty dict and emits a warning.

    Returns:
        {"memory_mb": float, "cpu_percent": float}
        or {} if psutil is unavailable.
    """
    try:
        import psutil  # type: ignore
    except ImportError:
        warnings.warn(
            "psutil is not installed. Resource tracking is disabled. "
            "Install it with:  pip install psutil",
            UserWarning,
            stacklevel=2,
        )
        return {}

    import os as _os

    target_pid = pid if pid is not None else _os.getpid()
    try:
        proc = psutil.Process(target_pid)
        mem_info = proc.memory_info()
        memory_mb = mem_info.rss / (1024 ** 2)
        cpu_percent = proc.cpu_percent(interval=0.05)
        return {"memory_mb": float(memory_mb), "cpu_percent": float(cpu_percent)}
    except psutil.NoSuchProcess:
        logger.warning("Process %d not found for resource tracking.", target_pid)
        return {}
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Resource tracking failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Worker function (module-level for pickle-ability)
# ---------------------------------------------------------------------------

# We store the simulate_fn in a module-level slot so multiprocessing workers
# can call it without pickling the callable directly (lambdas aren't picklable).
_SIMULATE_FN: Optional[Callable] = None


def _worker_fn(config: SceneConfig):
    """Executed in a worker process.

    Returns (scene_id, result_dict, None, "") on success, or
    (scene_id, None, error_str, reason) on failure.
    """
    try:
        result = _SIMULATE_FN(config)
        return (config.scene_id, result, None, "")
    except Exception as exc:  # pylint: disable=broad-except
        return (config.scene_id, None, str(exc), classify_failure(exc))


def _init_worker(simulate_fn: Callable) -> None:
    """Pool initialiser: stash simulate_fn in the global slot."""
    global _SIMULATE_FN
    _SIMULATE_FN = simulate_fn


# ---------------------------------------------------------------------------
# BatchExecutor
# ---------------------------------------------------------------------------


class BatchExecutor:
    """Execute a list of scene configs in parallel using multiprocessing.Pool.

    Throughput target: ≥ 1000 scenes/hour on an 8-core machine.

    Args:
        job_queue:    Iterable JobQueue of pending SceneConfig objects.
        worker_count: Number of parallel worker processes.
        output_dir:   Base output directory (created if absent).
        simulate_fn:  Callable(SceneConfig) → dict, the per-scene simulator.
    """

    def __init__(
        self,
        job_queue: JobQueue,
        worker_count: int,
        output_dir: str,
        simulate_fn: Callable,
    ) -> None:
        self._queue = job_queue
        self._worker_count = max(1, int(worker_count))
        self._output_dir = output_dir
        self._simulate_fn = simulate_fn

    # ------------------------------------------------------------------
    def run(self) -> ExecutionSummary:
        """Execute all pending jobs and return an ExecutionSummary.

        - ``worker_count == 1`` runs sequentially in-process; otherwise a
          multiprocessing.Pool is used.
        - Per-job exceptions are recorded with a reason and do NOT halt the batch.
        - The checkpoint is updated after every job (completed or failed).
        """
        import multiprocessing

        Path(self._output_dir).mkdir(parents=True, exist_ok=True)

        pending = list(self._queue)  # snapshot (verifies previous outputs)
        n_total = len(self._queue)
        n_pending = len(pending)
        skipped = self._queue.skipped_ids
        dup_groups = self._queue.duplicate_groups()
        for g in dup_groups:
            logger.warning("Scenes share one render fingerprint: %s", g)

        logger.info(
            "BatchExecutor starting: %d pending / %d total (%d verified skip), workers=%d",
            n_pending, n_total, len(skipped), self._worker_count,
        )

        n_completed = 0
        failed_ids: List[str] = []
        reasons: Dict[str, str] = {}
        audio_s = 0.0
        qc_audio_s = 0.0
        bytes_written = 0

        def _handle(scene_id, result, error, reason):
            nonlocal n_completed, audio_s, qc_audio_s, bytes_written
            if error is not None:
                failed_ids.append(scene_id)
                reasons[scene_id] = reason
                self._queue.mark_failed(scene_id, reason)
                logger.error("Scene %s FAILED (%s): %s", scene_id, reason, error)
                return
            n_completed += 1
            self._queue.mark_complete(scene_id)
            if isinstance(result, dict):
                dur = float(result.get("audio_duration_s", 0.0) or 0.0)
                audio_s += dur
                if (result.get("qc") or {}).get("passed", False):
                    qc_audio_s += dur
                bytes_written += int(result.get("bytes_written", 0) or 0)

        t_start = time.monotonic()
        if n_pending == 0:
            logger.info("No pending jobs.")
        elif self._worker_count == 1:
            _init_worker(self._simulate_fn)
            for cfg in pending:
                _handle(*_worker_fn(cfg))
        else:
            with multiprocessing.Pool(
                processes=min(self._worker_count, n_pending),
                initializer=_init_worker,
                initargs=(self._simulate_fn,),
            ) as pool:
                for item in pool.imap_unordered(_worker_fn, pending):
                    _handle(*item)

        elapsed = time.monotonic() - t_start
        total_done = n_completed + len(skipped)
        throughput = (n_completed / elapsed * 3600.0) if elapsed > 0 else float("inf")
        qc_rate = (qc_audio_s / 3600.0) / (elapsed / 3600.0) if elapsed > 0 else 0.0

        summary = ExecutionSummary(
            n_completed=total_done,
            n_failed=len(failed_ids),
            n_total=n_total,
            elapsed_s=elapsed,
            throughput_scenes_per_hour=throughput,
            failed_scene_ids=failed_ids,
            n_skipped=len(skipped),
            failure_reasons=reasons,
            audio_seconds_completed=audio_s,
            bytes_written=bytes_written,
            qc_passed_audio_hours_per_hour=qc_rate,
            duplicate_groups=dup_groups,
        )
        logger.info(
            "Batch done: %d completed (%d skipped), %d failed, %.2f s, %.1f scenes/h",
            total_done, len(skipped), len(failed_ids), elapsed, throughput,
        )
        return summary


# ---------------------------------------------------------------------------
# Convenience top-level function
# ---------------------------------------------------------------------------


def run_batch(
    configs: List[SceneConfig],
    worker_count: int,
    output_dir: str,
    simulate_fn: Callable,
    checkpoint_file: Optional[str] = None,
    verify: str = "checksum",
) -> ExecutionSummary:
    """High-level entry point combining JobQueue + BatchExecutor.

    Args:
        configs:         List of SceneConfig objects to process.
        worker_count:    Number of parallel worker processes.
        output_dir:      Directory where outputs will be written.
        simulate_fn:     Callable(SceneConfig) → dict.
        checkpoint_file: Optional path for checkpoint JSON (for resumption).

    Returns:
        ExecutionSummary with completion stats.
    """
    queue = JobQueue(configs, checkpoint_file=checkpoint_file, verify=verify)
    executor = BatchExecutor(
        job_queue=queue,
        worker_count=worker_count,
        output_dir=output_dir,
        simulate_fn=simulate_fn,
    )
    return executor.run()


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def _fake_simulate(cfg: SceneConfig) -> dict:
    """Smoke-test simulate_fn.  Module level so spawned workers can import it."""
    time.sleep(0.01)
    return {"scene_id": cfg.scene_id, "status": "ok"}


if __name__ == "__main__":
    import tempfile
    import os

    logging.basicConfig(level=logging.INFO)
    print("=== w152_batch smoke test ===")

    # Build minimal SceneConfig objects
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from simulator.types import SceneConfig  # noqa: F811

    cfgs = [
        SceneConfig(
            scene_id=f"smoke_{i:03d}",
            seed=i,
            schema_version="1.0.0",
            room={"type": "shoebox", "dimensions": {"L": 5.0, "W": 4.0, "H": 3.0}},
            materials={},
            sources=[{"source_id": "s1", "position": {"x": 1, "y": 1, "z": 1}}],
            receivers=[{"receiver_id": "r1", "position": {"x": 3, "y": 1, "z": 1}}],
        )
        for i in range(6)
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        ckpt = os.path.join(tmpdir, "ckpt.json")
        summary = run_batch(cfgs, worker_count=2, output_dir=tmpdir,
                            simulate_fn=_fake_simulate, checkpoint_file=ckpt, verify="none")
        print(f"  n_completed : {summary.n_completed}")
        print(f"  n_failed    : {summary.n_failed}")
        print(f"  elapsed_s   : {summary.elapsed_s:.3f}")
        print(f"  throughput  : {summary.throughput_scenes_per_hour:.1f} scenes/h")

    res = track_resource_usage()
    print(f"  resource_usage: {res}")

    print("  PASS")
