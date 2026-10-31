"""Publish the model's output to CloudWatch as custom metrics (optional).

CloudFormation creates an alarm on 'FailureRisk', so AWS itself can also notify
administrators. Failures here are logged and never break monitoring.
"""
import logging
from typing import Dict

logger = logging.getLogger("cloudwatch")
NAMESPACE = "CADMonitor"


class CloudWatchPublisher:
    def __init__(self, enabled: bool = False, region: str = "ap-south-1", project: str = "cad-monitor"):
        self.client = None
        self.project = project
        if enabled:
            try:
                import boto3
                self.client = boto3.client("cloudwatch", region_name=region)
            except Exception as exc:
                logger.error("CloudWatch init failed: %s", exc)

    def publish(self, r: Dict) -> None:
        if not self.client:
            return
        dims = [{"Name": "Project", "Value": self.project}]
        data = [
            {"MetricName": n, "Dimensions": dims, "Value": float(r[k]), "Unit": u}
            for n, k, u in [("FailureRisk", "failure_risk", "Percent"),
                            ("AnomalyScore", "anomaly_score", "None"),
                            ("CpuUtilization", "cpu", "Percent"),
                            ("MemoryUtilization", "memory", "Percent"),
                            ("DiskUtilization", "disk", "Percent")]
        ]
        try:
            self.client.put_metric_data(Namespace=NAMESPACE, MetricData=data)
        except Exception as exc:
            logger.error("CloudWatch put_metric_data failed: %s", exc)
