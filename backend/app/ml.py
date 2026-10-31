"""Machine-learning anomaly detection + failure-risk estimation.

Model: Isolation Forest (scikit-learn) inside a Pipeline with StandardScaler.
  * Trained on *normal* history only (unsupervised - no labels needed).
  * decision_function(x) < 0  -> anomaly.  The more negative, the stranger the sample.

Failure risk (0-100) combines two signals:
  * anomaly score      - how unusual the pattern is (from the ML model)
  * resource pressure  - how close CPU / memory / disk are to saturation
"""
import random
from typing import Dict, List, Optional

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .collector import FEATURES, baseline_sample

SCORE_SCALE = 0.10  # decision-function distance below 0 that maps to anomaly_score = 100


def severity_from_risk(risk: float) -> str:
    if risk >= 75:
        return "critical"
    if risk >= 55:
        return "high"
    if risk >= 30:
        return "warning"
    return "normal"


HEALTH_LABELS = {"critical": "Critical", "high": "At risk", "warning": "Degraded", "normal": "Healthy"}


def resource_pressure(sample: Dict[str, float]) -> float:
    """0-100: how close the most-loaded resource is to saturation (counts from 60%)."""
    worst = max(sample["cpu"], sample["memory"], sample["disk"])
    return float(np.clip((worst - 60.0) / 40.0 * 100.0, 0, 100))


def raw_vector(sample: Dict[str, float]) -> List[float]:
    return [float(sample[f]) for f in FEATURES]


def to_vector(sample: Dict[str, float]) -> List[float]:
    """Model input = 5 raw metrics + 2 engineered features.

    Isolation Forest picks features at random, so a spike in just one metric is easy to
    miss. 'peak_util' (worst of CPU/memory/disk) and 'net_total' make every resource
    problem visible through a dedicated feature (found by experiment - see docs/REPORT.md).
    """
    raw = raw_vector(sample)
    peak_util = max(sample["cpu"], sample["memory"], sample["disk"])
    net_total = sample["net_in"] + sample["net_out"]
    return raw + [peak_util, net_total]


class AnomalyDetector:
    def __init__(self, contamination=0.05, random_state: int = 42):
        self.contamination = contamination
        self.random_state = random_state
        self.pipeline = None
        self.trained_on = 0
        self.version = 0

    @property
    def is_trained(self) -> bool:
        return self.pipeline is not None

    def train(self, samples: List[Dict[str, float]]) -> None:
        X = np.array([to_vector(s) for s in samples])
        pipe = make_pipeline(
            StandardScaler(),
            IsolationForest(n_estimators=150, contamination=self.contamination,
                            random_state=self.random_state),
        )
        pipe.fit(X)
        self.pipeline = pipe
        self.trained_on = len(samples)
        self.version += 1

    def train_on_synthetic_baseline(self, n: int = 400, seed: int = 7) -> None:
        """Bootstrap with simulated healthy behaviour so the demo works immediately."""
        rng = random.Random(seed)
        self.train([baseline_sample(i, rng) for i in range(n)])

    def analyse(self, sample: Dict[str, float]) -> Dict[str, object]:
        """Return anomaly decision, 0-100 anomaly score, failure risk and severity."""
        if not self.is_trained:
            return {"ready": False, "is_anomaly": False, "raw_score": 0.0, "anomaly_score": 0.0,
                    "failure_risk": 0.0, "severity": "normal"}
        d = float(self.pipeline.decision_function(np.array([to_vector(sample)]))[0])
        anomaly_score = float(np.clip(-d / SCORE_SCALE, 0, 1) * 100)
        risk = float(np.clip(0.5 * anomaly_score + 0.5 * resource_pressure(sample), 0, 100))
        return {
            "ready": True,
            "is_anomaly": d < 0,
            "raw_score": round(d, 4),
            "anomaly_score": round(anomaly_score, 1),
            "failure_risk": round(risk, 1),
            "severity": severity_from_risk(risk),
        }

    def culprit(self, sample: Dict[str, float], baseline: Optional[List[Dict[str, float]]]) -> str:
        """Name the metric deviating most from the recent normal baseline (z-score)."""
        if not baseline or len(baseline) < 10:
            return "unknown"
        arr = np.array([raw_vector(b) for b in baseline])
        z = np.abs((np.array(raw_vector(sample)) - arr.mean(axis=0)) / (arr.std(axis=0) + 1e-6))
        return FEATURES[int(z.argmax())]
