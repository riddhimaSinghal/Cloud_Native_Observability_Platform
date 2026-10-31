from app.collector import Collector
from app.ml import AnomalyDetector, severity_from_risk


def trained():
    d = AnomalyDetector()
    d.train_on_synthetic_baseline()
    return d


def test_untrained_model_is_not_ready():
    assert AnomalyDetector().analyse({"cpu": 1, "memory": 1, "disk": 1, "net_in": 1, "net_out": 1})["ready"] is False


def test_normal_traffic_mostly_not_flagged():
    d, c = trained(), Collector(seed=1)
    results = [d.analyse(c.collect()) for _ in range(200)]
    assert sum(r["is_anomaly"] for r in results) / 200 < 0.10
    assert sum(r["severity"] in ("high", "critical") for r in results) == 0


def test_every_scenario_is_detected():
    d = trained()
    for name in ["cpu_spike", "memory_leak", "disk_fill", "network_flood", "full_failure"]:
        c = Collector(seed=2)
        c.start_scenario(name)
        results = [d.analyse(c.collect()) for _ in range(20)]
        assert sum(r["is_anomaly"] for r in results) >= 6, name
        assert max(r["failure_risk"] for r in results) >= 40, name


def test_full_failure_is_critical():
    d, c = trained(), Collector(seed=3)
    c.start_scenario("full_failure")
    assert all(d.analyse(c.collect())["severity"] == "critical" for _ in range(10))


def test_severity_bands():
    assert [severity_from_risk(x) for x in (0, 40, 60, 90)] == ["normal", "warning", "high", "critical"]


def test_retraining_increments_version():
    d = trained()
    v = d.version
    d.train_on_synthetic_baseline(n=100, seed=1)
    assert d.version == v + 1
