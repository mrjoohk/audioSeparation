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
    """Thread/process-safe (single-writer) job queue with checkpoint support.

    Usage::

        queue = JobQueue(configs, checkpoint_file="ckpt.json")
        for cfg in queue:
            result = simulate(cfg)
            queue.mark_complete(cfg.scene_id)
    """

    def __init__(
        self,
        configs: List[SceneConfig],
        checkpoint_file: Optional[str] = None,
    ) -> None:
        self._configs: List[SceneConfig] = list(configs)
        self._checkpoint_file: Optional[str] = checkpoint_file
        self._completed_ids: set = set()

        # Load existing checkpoint if present
        if checkpoint_file:
            self.load_checkpoint()

    # ------------------------------------------------------------------
    def load_checkpoint(self) -> None:
        """Read checkpoint_file (JSON list of completed scene_ids) and
        mark those IDs as already completed so they are skipped during
        iteration."""
        if not self._checkpoint_file:
            return
        p = Path(self._checkpoint_file)
        if not p.exists():
            logger.debug("No checkpoint file found at %s — starting fresh.", p)
            return
        try:
            with p.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                self._completed_ids.update(data)
                logger.info(
                    "Checkpoint loaded: %d scene(s) already completed.",
                    len(self._completed_ids),
                )
            else:
                logger.warning("Checkpoint file has unexpected format; ignoring.")
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to load checkpoint: %s", exc)

    def save_checkpoint(self, completed_ids: List[str]) -> None:
        """Write *completed_ids* to checkpoint_file as a JSON array."""
        if not self._checkpoint_file:
            return
        p = Path(self._checkpoint_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with p.open("w", encoding="utf-8") as fh:
                json.dump(sorted(completed_ids), fh, indent=2)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to save checkpoint: %s", exc)

    # ------------------------------------------------------------------
    def mark_complete(self, scene_id: str) -> None:
        """Record *scene_id* as completed and persist the checkpoint."""
        self._completed_ids.add(scene_id)
        self.save_checkpoint(list(self._completed_ids))

    # ------------------------------------------------------------------
    @property
    def pending_count(self) -> int:
        """Number of configs not yet completed."""
        return sum(
            1 for cfg in self._configs if cfg.scene_id not in self._completed_ids
        )

    # ------------------------------------------------------------------
    def __iter__(self):
        """Yield pending SceneConfig objects (skip already completed)."""
        for cfg in self._configs:
            if cfg.scene_id not in self._completed_ids:
                yield cfg

    def __len__(self) -> int:
        return len(self._configs)


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
    """Executed in a worker process. Returns (scene_id, result_dict, None) on
    success, or (scene_id, None, error_str) on failure."""
    try:
        result = _SIMULATE_FN(config)
        return (config.scene_id, result, None)
    except Exception as exc:  # pylint: disable=broad-except
        return (config.scene_id, None, str(exc))


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

        - Uses multiprocessing.Pool for parallelism.
        - Per-job exceptions are logged but do NOT halt the batch.
        - Checkpoint is saved after every completed job.
        - Tracks elapsed time and computes throughput.
        """
        import multiprocessing

        Path(self._output_dir).mkdir(parents=True, exist_ok=True)

        pending = list(self._queue)  # snapshot
        n_total = len(self._queue)  # includes already-completed
        n_pending = len(pending)

        logger.info(
            "BatchExecutor starting: %d pending / %d total, workers=%d",
            n_pending,
            n_total,
            self._worker_count,
        )

        n_completed = 0
        n_failed = 0
        failed_ids: List[str] = []

        t_start = time.monotonic()

        if n_pending == 0:
            logger.info("No pending jobs.")
        else:
            with multiprocessing.Pool(
                processes=self._worker_count,
                initializer=_init_worker,
                initargs=(self._simulate_fn,),
            ) as pool:
                # imap_unordered gives results as they complete → good for
                # checkpointing and progress logging.
                for scene_id, result, error in pool.imap_unordered(
                    _worker_fn, pending
                ):
                    if error is not None:
                        n_failed += 1
                        failed_ids.append(scene_id)
                        logger.error(
                            "Scene %s FAILED: %s", scene_id, error
                        )
                    else:
                        n_completed += 1
                        self._queue.mark_complete(scene_id)
                        logger.debug("Scene %s completed.", scene_id)

        elapsed = time.monotonic() - t_start
        # Add scenes that were already complete before this run
        already_done = n_total - n_pending
        total_done = n_completed + already_done

        throughput = (n_completed / elapsed * 3600.0) if elapsed > 0 else float("inf")

        summary = ExecutionSummary(
            n_completed=total_done,
            n_failed=n_failed,
            n_total=n_total,
            elapsed_s=elapsed,
            throughput_scenes_per_hour=throughput,
            failed_scene_ids=failed_ids,
        )

        logger.info(
            "Batch done: %d completed, %d failed, %.2f s, %.1f scenes/h",
            total_done,
            n_failed,
            elapsed,
            throughput,
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
    queue = JobQueue(configs, checkpoint_file=checkpoint_file)
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

if __name__ == "__main__":
    import tempfile
    import os

    logging.basicConfig(level=logging.INFO)
    print("=== w152_batch smoke test ===")

    # Build minimal SceneConfig objects
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from simulator.types import SceneConfig  # noqa: F811

    def _fake_simulate(cfg: SceneConfig) -> dict:
        # Simulate a tiny amount of work
        time.sleep(0.01)
        return {"scene_id": cfg.scene_id, "status": "ok"}

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
                            simulate_fn=_fake_simulate, checkpoint_file=ckpt)
        print(f"  n_completed : {summary.n_completed}")
        print(f"  n_failed    : {summary.n_failed}")
        print(f"  elapsed_s   : {summary.elapsed_s:.3f}")
        print(f"  throughput  : {summary.throughput_scenes_per_hour:.1f} scenes/h")

    res = track_resource_usage()
    print(f"  resource_usage: {res}")

    print("  PASS")
