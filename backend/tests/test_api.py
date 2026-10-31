"""End-to-end workflow test: metrics -> anomaly -> dashboard data -> alert."""
import pytest
from fastapi.testclient import TestClient

from app.alerts import Alerter
from app.collector import Collector
from app.config import Settings
from app.engine import MonitoringEngine
from app.main import create_app

KEY = {"X-API-Key": "test-key"}


@pytest.fixture()
def env():
    s = Settings(auto_start_loop=False, api_key="test-key", alert_cooldown_seconds=0, alert_consecutive=2)
    eng = MonitoringEngine(s, collector=Collector("simulated", seed=5), alerter=Alerter("", cooldown=0, consecutive=2))
    return eng, TestClient(create_app(s, eng))


def test_health_and_overview(env):
    eng, c = env
    for _ in range(5):
        eng.step()
    assert c.get("/api/health").json()["status"] == "ok"
    data = c.get("/api/overview").json()
    assert data["server"]["status"] == "Healthy"
    assert len(data["history"]) == 5 and data["model"]["trained"]


def test_simulate_requires_api_key(env):
    _, c = env
    assert c.post("/api/simulate", json={"scenario": "cpu_spike"}).status_code == 401
    assert c.post("/api/simulate", json={"scenario": "cpu_spike"}, headers={"X-API-Key": "wrong"}).status_code == 401


def test_invalid_scenario_rejected(env):
    _, c = env
    assert c.post("/api/simulate", json={"scenario": "rm -rf"}, headers=KEY).status_code == 422


def test_query_limits_validated(env):
    _, c = env
    assert c.get("/api/overview?history=999999").status_code == 422


def test_full_workflow(env):
    eng, c = env
    for _ in range(30):
        eng.step()
    assert c.get("/api/overview").json()["server"]["severity"] == "normal"
    assert c.post("/api/simulate", json={"scenario": "full_failure"}, headers=KEY).status_code == 200
    for _ in range(15):
        eng.step()
    data = c.get("/api/overview").json()
    assert data["server"]["severity"] == "critical"          # dashboard reflects failure
    assert data["anomalies"], "anomaly history should have entries"
    assert data["alerts"], "an alert should have been generated"
    assert data["alerts"][0]["severity"] == "critical"
    assert data["latest"]["injected"] is True


def test_stop_and_retrain(env):
    eng, c = env
    for _ in range(80):
        eng.step()
    c.post("/api/simulate", json={"scenario": "cpu_spike"}, headers=KEY)
    assert c.post("/api/simulate/stop", headers=KEY).json()["stopped"]
    assert c.post("/api/retrain", headers=KEY).status_code == 200


def test_monitoring_survives_collector_error(env):
    eng, _ = env
    original = eng.collector.collect
    eng.collector.collect = lambda: (_ for _ in ()).throw(RuntimeError("sensor down"))
    with pytest.raises(RuntimeError):
        eng.step()               # the API loop catches this and keeps running
    eng.collector.collect = original
    assert eng.step()["cpu"] >= 0
