from app.config import Settings
from app.engine import MonitoringEngine


def test_real_mode_learns_then_detects():
    """In 'real' mode the model trains itself on the first N live samples (psutil)."""
    eng = MonitoringEngine(Settings(auto_start_loop=False, metrics_source="real", min_train_samples=10))
    assert not eng.detector.is_trained
    assert eng.overview()["server"]["status"] == "Learning"
    for _ in range(12):
        eng.step()
    assert eng.detector.is_trained
    r = eng.step()
    assert r["ready"] and 0 <= r["cpu"] <= 100
