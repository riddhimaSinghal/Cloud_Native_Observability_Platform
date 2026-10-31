"""Alerting: send an email through AWS SNS when a critical anomaly persists.

Safeguards:
  * needs N consecutive critical samples (avoids alerting on a single blip)
  * cool-down between alerts (avoids an email storm)
  * if SNS is not configured or fails, the alert is still recorded + logged
"""
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger("alerts")


class Alerter:
    def __init__(self, topic_arn: str = "", region: str = "ap-south-1",
                 cooldown: int = 60, consecutive: int = 2, client=None):
        self.topic_arn = topic_arn
        self.cooldown = cooldown
        self.consecutive = consecutive
        self._streak = 0
        self._last_sent = 0.0
        self._client = client
        if topic_arn and client is None:
            try:
                import boto3
                self._client = boto3.client("sns", region_name=region)
            except Exception as exc:
                logger.error("SNS client init failed: %s", exc)

    def evaluate(self, record: Dict) -> Optional[Dict]:
        """Call once per sample. Returns an alert dict if one was raised, else None."""
        if record["severity"] == "critical":
            self._streak += 1
        else:
            self._streak = 0
            return None
        now = time.time()
        if self._streak < self.consecutive or now - self._last_sent < self.cooldown:
            return None
        self._last_sent = now
        return self._raise(record)

    def _raise(self, r: Dict) -> Dict:
        subject = f"[CRITICAL] {r['server_id']}: failure risk {r['failure_risk']:.0f}%"
        body = (
            f"Critical anomaly detected by the AI monitoring platform.\n\n"
            f"Server        : {r['server_id']}\n"
            f"Time (UTC)    : {r['timestamp']}\n"
            f"Failure risk  : {r['failure_risk']}%\n"
            f"Anomaly score : {r['anomaly_score']}/100\n"
            f"Main cause    : {r.get('culprit_label', 'unknown')}\n"
            f"CPU {r['cpu']}% | Memory {r['memory']}% | Disk {r['disk']}%\n"
            f"Network in/out: {r['net_in']} / {r['net_out']} KB/s\n"
            f"{'NOTE: this event was injected by the demo simulator.' if r['injected'] else ''}\n"
            f"\nRecommended action: investigate the server before it becomes unavailable."
        )
        status = "logged-locally"
        if self._client and self.topic_arn:
            try:
                self._client.publish(TopicArn=self.topic_arn, Subject=subject[:99], Message=body)
                status = "sent-via-sns"
            except Exception as exc:
                status = "sns-failed"
                logger.error("SNS publish failed: %s", exc)
        logger.warning("ALERT (%s): %s", status, subject)
        return {
            "id": uuid.uuid4().hex[:8],
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "server_id": r["server_id"], "severity": "critical",
            "failure_risk": r["failure_risk"], "subject": subject, "delivery": status,
        }
