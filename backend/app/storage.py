"""Storage: fast in-memory history (always) + optional DynamoDB persistence."""
import logging
import threading
import time
from collections import deque
from decimal import Decimal
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("storage")
TTL_SECONDS = 24 * 3600  # DynamoDB TTL: old metric rows expire automatically


def _to_dynamo(obj: Any) -> Any:
    """boto3 needs Decimal instead of float."""
    if isinstance(obj, float):
        return Decimal(str(round(obj, 4)))
    if isinstance(obj, dict):
        return {k: _to_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dynamo(v) for v in obj]
    return obj


class Store:
    def __init__(self, history_size: int = 1000, region: str = "ap-south-1",
                 metrics_table: str = "", alerts_table: str = ""):
        self._lock = threading.Lock()
        self.samples: Deque[Dict] = deque(maxlen=history_size)
        self.anomalies: Deque[Dict] = deque(maxlen=200)
        self.alerts: Deque[Dict] = deque(maxlen=200)
        self._metrics_tbl = self._alerts_tbl = None
        if metrics_table or alerts_table:
            try:
                import boto3
                ddb = boto3.resource("dynamodb", region_name=region)
                self._metrics_tbl = ddb.Table(metrics_table) if metrics_table else None
                self._alerts_tbl = ddb.Table(alerts_table) if alerts_table else None
                logger.info("DynamoDB persistence enabled")
            except Exception as exc:  # never crash the app because of AWS
                logger.error("DynamoDB init failed, using memory only: %s", exc)

    @property
    def dynamodb_enabled(self) -> bool:
        return bool(self._metrics_tbl or self._alerts_tbl)

    # ----- writes -----
    def add_sample(self, sample: Dict) -> None:
        with self._lock:
            self.samples.append(sample)
        if self._metrics_tbl:
            self._put(self._metrics_tbl, {"server_id": sample["server_id"], **sample,
                                          "expires_at": int(time.time()) + TTL_SECONDS})

    def add_anomaly(self, event: Dict) -> None:
        with self._lock:
            self.anomalies.append(event)

    def add_alert(self, alert: Dict) -> None:
        with self._lock:
            self.alerts.append(alert)
        if self._alerts_tbl:
            self._put(self._alerts_tbl, {"server_id": alert["server_id"], **alert})

    def _put(self, table, item: Dict) -> None:
        try:
            table.put_item(Item=_to_dynamo(item))
        except Exception as exc:
            logger.error("DynamoDB write failed: %s", exc)

    # ----- reads (return copies) -----
    def recent_samples(self, limit: int = 120) -> List[Dict]:
        with self._lock:
            return list(self.samples)[-limit:]

    def recent_normal(self, limit: int = 400) -> List[Dict]:
        """Samples suitable for (re)training: no injected faults, not flagged as high risk."""
        with self._lock:
            ok = [s for s in self.samples if not s["injected"] and s["severity"] in ("normal", "warning")
                  and not (s["is_anomaly"] and s["severity"] == "warning")]
        return ok[-limit:]

    def recent_anomalies(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            return list(self.anomalies)[-limit:][::-1]

    def recent_alerts(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            return list(self.alerts)[-limit:][::-1]

    def count(self) -> int:
        with self._lock:
            return len(self.samples)
