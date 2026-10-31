"""Reproduce the model evaluation quoted in docs/REPORT.md:  python evaluate_model.py"""
from app.collector import Collector, SCENARIOS
from app.ml import AnomalyDetector

det = AnomalyDetector()
det.train_on_synthetic_baseline()

c = Collector(seed=1)
normal = [det.analyse(c.collect()) for _ in range(500)]
fp = sum(r["is_anomaly"] for r in normal) / len(normal)
print(f"Healthy data: {len(normal)} samples, flagged as anomaly: {fp:.1%}, "
      f"max severity reached: {max(normal, key=lambda r: r['failure_risk'])['severity']}")
print(f"\n{'scenario':15} {'anomalous':>10} {'max risk':>9} {'worst severity':>15}")
order = ["normal", "warning", "high", "critical"]
for name in SCENARIOS:
    c = Collector(seed=2)
    c.start_scenario(name)
    rs = [det.analyse(c.collect()) for _ in range(20)]
    worst = max((r["severity"] for r in rs), key=order.index)
    print(f"{name:15} {sum(r['is_anomaly'] for r in rs):>7}/20 {max(r['failure_risk'] for r in rs):>9.1f} {worst:>15}")
