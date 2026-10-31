"""The monitoring engine: collect -> analyse -> store -> alert. One call to step() = one cycle."""
import logging
import socket
from datetime import datetime, timezone
from typing import Dict, Optional

from .alerts import Alerter
from .cloudwatch import CloudWatchPublisher
from .collector import Collector, SCENARIOS
from .config import Settings
from .ml import AnomalyDetector, HEALTH_LABELS
from .storage import Store

logger = logging.getLogger("engine")
LABELS = {"cpu": "CPU", "memory": "Memory", "disk": "Disk", "net_in": "Inbound network",
          "net_out": "Outbound network", "unknown": "Unknown"}
SEV_ORDER = {"normal": 0, "warning": 1, "high": 2, "critical": 3}


class MonitoringEngine:
    def __init__(self, settings: Settings, collector: Optional[Collector] = None,
                 alerter: Optional[Alerter] = None):
        self.settings = settings
        self.server_id = socket.gethostname()
        self.collector = collector or Collector(settings.metrics_source)
        self.detector = AnomalyDetector()
        self.store = Store(settings.history_size, settings.aws_region,
                           settings.dynamodb_metrics_table, settings.dynamodb_alerts_table)
        self.alerter = alerter or Alerter(settings.sns_topic_arn, settings.aws_region,
                                          settings.alert_cooldown_seconds, settings.alert_consecutive)
        self.cw = CloudWatchPublisher(settings.cloudwatch_enabled, settings.aws_region, settings.cloudwatch_project)
        self._episode_sev = "normal"   # worst severity logged in the current anomaly episode
        self._anomaly_streak = 0
        self._clean_streak = 0
        self._steps = 0
        self.last_error: Optional[str] = None
        if settings.metrics_source == "simulated":
            self.detector.train_on_synthetic_baseline()  # ready immediately for the demo

    # ---------- one monitoring cycle ----------
    def step(self) -> Dict:
        raw = self.collector.collect()
        result = self.detector.analyse(raw)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "server_id": self.server_id, **raw, **result,
        }
        # warm-up training in 'real' mode: learn from the first N samples
        if not self.detector.is_trained and self.store.count() + 1 >= self.settings.min_train_samples:
            self.store.add_sample({**record, "severity": "normal", "is_anomaly": False})
            self.detector.train(self.store.recent_samples(self.settings.history_size))
            self._steps += 1
            return record

        if result["is_anomaly"] and result["severity"] != "normal":
            record["culprit"] = self.detector.culprit(raw, self.store.recent_normal(100))
            record["culprit_label"] = LABELS[record["culprit"]]
        self.store.add_sample(record)
        self._steps += 1

        # Log an anomaly event once an anomaly persists for 2+ samples (filters one-off noise),
        # and again if the severity escalates during the same episode.
        sev = record["severity"]
        if result["is_anomaly"] and sev != "normal":
            self._anomaly_streak += 1
            self._clean_streak = 0
        else:
            self._clean_streak += 1
            if self._clean_streak >= 3:
                self._anomaly_streak, self._episode_sev = 0, "normal"
        if self._anomaly_streak >= 2 and SEV_ORDER[sev] > SEV_ORDER[self._episode_sev]:
            self._episode_sev = sev
            culprit = record.get("culprit_label", "Unknown")
            self.store.add_anomaly({
                "timestamp": record["timestamp"], "severity": sev,
                "failure_risk": record["failure_risk"], "anomaly_score": record["anomaly_score"],
                "culprit": culprit, "injected": record["injected"],
                "summary": f"{culprit} behaving abnormally "
                           f"(CPU {record['cpu']}%, Mem {record['memory']}%, Disk {record['disk']}%)",
            })

        alert = self.alerter.evaluate(record)
        if alert:
            self.store.add_alert(alert)
        self.cw.publish(record)

        if self.detector.is_trained and self._steps % self.settings.retrain_every == 0:
            self.retrain()
        return record

    def retrain(self) -> int:
        normal = self.store.recent_normal()
        if len(normal) < 50:
            raise ValueError("Not enough normal samples to retrain yet")
        self.detector.train(normal)
        logger.info("Model retrained on %d samples (v%d)", len(normal), self.detector.version)
        return len(normal)

    # ---------- views for the API ----------
    def overview(self, history: int = 120) -> Dict:
        samples = self.store.recent_samples(history)
        latest = samples[-1] if samples else None
        sc = self.collector.scenario
        risk = latest["failure_risk"] if latest else 0
        return {
            "server": {
                "id": self.server_id,
                "status": HEALTH_LABELS[latest["severity"]] if latest and self.detector.is_trained else "Learning",
                "severity": latest["severity"] if latest else "normal",
                "failure_risk": risk,
                "metrics_source": self.settings.metrics_source,
            },
            "latest": latest,
            "history": samples,
            "anomalies": self.store.recent_anomalies(20),
            "alerts": self.store.recent_alerts(20),
            "model": {
                "type": "Isolation Forest (scikit-learn)",
                "trained": self.detector.is_trained, "trained_on": self.detector.trained_on,
                "version": self.detector.version,
                "warmup_remaining": 0 if self.detector.is_trained else
                max(0, self.settings.min_train_samples - self.store.count()),
            },
            "simulation": {"active": sc.name if sc else None,
                           "remaining": (sc.total - sc.elapsed) if sc else 0},
            "integrations": {"sns": bool(self.alerter.topic_arn), "dynamodb": self.store.dynamodb_enabled,
                             "cloudwatch": self.cw.client is not None},
            "scenarios": SCENARIOS,
        }
