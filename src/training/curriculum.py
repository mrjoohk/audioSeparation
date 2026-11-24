"""
Mixed-domain curriculum sampling with prefetching (REQ-301).

* Each batch draws items from domains (e.g. "synthetic", "real") with target
  weights.  Counts per batch are allocated by largest remainder with a running
  correction, so the cumulative domain ratio stays at the target (±5 %).
* A curriculum moves the synthetic difficulty-tier weights from ``start`` to
  ``end`` over ``ramp_steps`` steps (e.g. easy → hard overlap).
* :class:`Prefetcher` loads the next batches on a background thread so the
  training step does not wait on I/O; it reports the fraction of time the
  consumer waited (REQ-301: < 5 %).
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import numpy as np


@dataclass
class Curriculum:
    start: Mapping[str, float]                 # tier -> weight at step 0
    end: Mapping[str, float]                   # tier -> weight at ramp end
    ramp_steps: int = 1000

    def weights(self, step: int) -> Dict[str, float]:
        a = min(1.0, max(0.0, step / max(1, self.ramp_steps)))
        tiers = sorted(set(self.start) | set(self.end))
        w = {t: (1 - a) * self.start.get(t, 0.0) + a * self.end.get(t, 0.0) for t in tiers}
        z = sum(w.values()) or 1.0
        return {t: v / z for t, v in w.items()}


@dataclass
class MixedDomainSampler:
    """Yields batches of (domain, item_id).

    Args:
        pools: domain -> list of item ids; for a curriculum domain, items may be
            given per tier via ``tiers`` (domain -> tier -> ids).
        weights: domain -> sampling weight (normalised).
    """
    pools: Mapping[str, Sequence[str]]
    weights: Mapping[str, float]
    batch_size: int = 8
    seed: int = 0
    tiers: Optional[Mapping[str, Mapping[str, Sequence[str]]]] = None
    curriculum: Optional[Curriculum] = None
    counts: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        z = sum(self.weights.values())
        self._w = {d: w / z for d, w in self.weights.items() if w > 0}
        for d in self._w:
            if not self.pools.get(d) and not (self.tiers and self.tiers.get(d)):
                raise ValueError(f"domain {d!r} has weight but no items")
        self._rng = np.random.default_rng(self.seed)
        self.counts = {d: 0 for d in self._w}
        self.step = 0

    def _allocate(self) -> Dict[str, int]:
        total = sum(self.counts.values()) + self.batch_size
        want = {d: w * total - self.counts[d] for d, w in self._w.items()}
        base = {d: max(0, int(np.floor(v))) for d, v in want.items()}
        rem = self.batch_size - sum(base.values())
        order = sorted(want, key=lambda d: want[d] - base[d], reverse=True)
        i = 0
        while rem > 0:
            base[order[i % len(order)]] += 1
            rem -= 1
            i += 1
        while sum(base.values()) > self.batch_size:          # can happen if want < 0
            d = max(base, key=lambda k: base[k] - want[k])
            base[d] -= 1
        return base

    def _draw(self, domain: str) -> str:
        if self.tiers and domain in self.tiers and self.curriculum is not None:
            tw = self.curriculum.weights(self.step)
            avail = [t for t in tw if self.tiers[domain].get(t)]
            p = np.array([tw[t] for t in avail], float)
            t = avail[int(self._rng.choice(len(avail), p=p / p.sum()))]
            ids = self.tiers[domain][t]
        else:
            ids = self.pools[domain]
        return ids[int(self._rng.integers(len(ids)))]

    def next_batch(self) -> List[Tuple[str, str]]:
        alloc = self._allocate()
        batch = [(d, self._draw(d)) for d, k in alloc.items() for _ in range(k)]
        self._rng.shuffle(batch)
        for d, k in alloc.items():
            self.counts[d] += k
        self.step += 1
        return batch

    def __iter__(self) -> Iterator[List[Tuple[str, str]]]:
        while True:
            yield self.next_batch()

    def ratios(self) -> Dict[str, float]:
        n = sum(self.counts.values()) or 1
        return {d: c / n for d, c in self.counts.items()}


class Prefetcher:
    """Background loading of batches; measures consumer wait time."""

    def __init__(self, sampler: MixedDomainSampler, load: Callable[[Tuple[str, str]], object],
                 depth: int = 8, workers: int = 2):
        self._q: "queue.Queue" = queue.Queue(maxsize=depth)
        self._load = load
        self._sampler = sampler
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.wait_s = 0.0
        self.total_s = 0.0
        self._t_last: Optional[float] = None
        self._threads = [threading.Thread(target=self._run, daemon=True) for _ in range(workers)]
        for t in self._threads:
            t.start()

    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                batch = self._sampler.next_batch()
            loaded = [(d, i, self._load((d, i))) for d, i in batch]
            while not self._stop.is_set():
                try:
                    self._q.put(loaded, timeout=0.1)
                    break
                except queue.Full:
                    continue

    def get(self):
        now = time.perf_counter()
        if self._t_last is not None:
            self.total_s += now - self._t_last
        t0 = time.perf_counter()
        item = self._q.get()
        waited = time.perf_counter() - t0
        self.wait_s += waited
        self.total_s += waited
        self._t_last = time.perf_counter()
        return item

    @property
    def wait_fraction(self) -> float:
        return self.wait_s / self.total_s if self.total_s > 0 else 0.0

    def close(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=1.0)
