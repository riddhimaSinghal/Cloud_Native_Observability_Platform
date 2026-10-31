"""Metric collection.

Two sources:
  * "real"      - reads this machine's CPU / memory / disk / network with psutil
  * "simulated" - generates realistic synthetic baseline data (for demos without AWS)

Both support *scenario injection*: an overlay that pushes metrics into abnormal
territory so the full workflow can be demonstrated on demand. Samples produced
while a scenario is active are flagged ``injected=True`` so the UI is honest about it.
"""
import math
import random
import time
from dataclasses import dataclass
from typing import Dict, Optional

import psutil

FEATURES = ["cpu", "memory", "disk", "net_in", "net_out"]  # order used by the ML model

SCENARIOS: Dict[str, str] = {
    "cpu_spike": "CPU jumps to ~95% (runaway process)",
    "memory_leak": "Memory climbs steadily towards 100%",
    "disk_fill": "Disk usage climbs quickly (log flood)",
    "network_flood": "Network traffic surges (possible DDoS)",
    "full_failure": "CPU, memory and network all go abnormal at once",
}
SCENARIO_TICKS = 20  # how many samples a scenario lasts


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


@dataclass
class ActiveScenario:
    name: str
    total: int
    elapsed: int = 0

    @property
    def progress(self) -> float:
        """Ramp from 0 to 1 over the first 40% of the scenario, then hold."""
        return min(1.0, (self.elapsed + 1) / max(1.0, self.total * 0.4))


def baseline_sample(t: float, rng: random.Random) -> Dict[str, float]:
    """Synthetic 'healthy server' behaviour: slow wave plus noise."""
    wave = math.sin(t / 40.0)
    return {
        "cpu": clamp(32 + 6 * wave + rng.gauss(0, 3)),
        "memory": clamp(55 + 3 * wave + rng.gauss(0, 1.5)),
        "disk": clamp(46 + rng.gauss(0, 0.3)),
        "net_in": max(0.0, 220 + 40 * wave + rng.gauss(0, 25)),   # KB/s
        "net_out": max(0.0, 140 + 25 * wave + rng.gauss(0, 18)),  # KB/s
    }


class Collector:
    def __init__(self, source: str = "simulated", seed: Optional[int] = None):
        self.source = source
        self.rng = random.Random(seed)
        self.scenario: Optional[ActiveScenario] = None
        self._tick = 0
        self._last_net = None  # (timestamp, bytes_recv, bytes_sent)
        if source == "real":
            psutil.cpu_percent(interval=None)  # prime the counter

    # ---------- scenario control ----------
    def start_scenario(self, name: str, ticks: int = SCENARIO_TICKS) -> None:
        if name not in SCENARIOS:
            raise ValueError(f"Unknown scenario: {name}")
        self.scenario = ActiveScenario(name=name, total=ticks)

    def stop_scenario(self) -> None:
        self.scenario = None

    # ---------- reading ----------
    def _read_real(self) -> Dict[str, float]:
        now = time.time()
        net = psutil.net_io_counters()
        kb_in = kb_out = 0.0
        if self._last_net:
            dt = max(now - self._last_net[0], 1e-3)
            kb_in = (net.bytes_recv - self._last_net[1]) / 1024 / dt
            kb_out = (net.bytes_sent - self._last_net[2]) / 1024 / dt
        self._last_net = (now, net.bytes_recv, net.bytes_sent)
        return {
            "cpu": psutil.cpu_percent(interval=None),
            "memory": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage("/").percent,
            "net_in": max(0.0, kb_in),
            "net_out": max(0.0, kb_out),
        }

    def _apply_scenario(self, m: Dict[str, float]) -> bool:
        s = self.scenario
        if not s:
            return False
        p = s.progress
        r = self.rng
        if s.name == "cpu_spike":
            m["cpu"] = clamp(96 + r.gauss(0, 2))
        elif s.name == "memory_leak":
            m["memory"] = clamp(m["memory"] + 42 * p + r.gauss(0, 1))
        elif s.name == "disk_fill":
            m["disk"] = clamp(m["disk"] + 48 * p)
        elif s.name == "network_flood":
            m["net_in"] *= 1 + 14 * p
            m["net_out"] *= 1 + 8 * p
        elif s.name == "full_failure":
            m["cpu"] = clamp(97 + r.gauss(0, 1.5))
            m["memory"] = clamp(m["memory"] + 38 * p)
            m["net_in"] *= 1 + 10 * p
        s.elapsed += 1
        if s.elapsed >= s.total:
            self.scenario = None
        return True

    def collect(self) -> Dict[str, object]:
        self._tick += 1
        m = self._read_real() if self.source == "real" else baseline_sample(self._tick, self.rng)
        injected = self._apply_scenario(m)
        out: Dict[str, object] = {k: round(float(v), 2) for k, v in m.items()}
        out["injected"] = injected
        return out
