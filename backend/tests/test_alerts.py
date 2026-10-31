from app.alerts import Alerter


class FakeSNS:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def publish(self, **kw):
        if self.fail:
            raise RuntimeError("boom")
        self.calls.append(kw)


def rec(sev="critical"):
    return {"severity": sev, "server_id": "s1", "timestamp": "t", "failure_risk": 95, "anomaly_score": 90,
            "cpu": 99, "memory": 90, "disk": 50, "net_in": 1, "net_out": 1, "injected": True,
            "culprit_label": "CPU"}


def test_needs_consecutive_critical_samples():
    sns = FakeSNS()
    a = Alerter("arn:x", consecutive=2, cooldown=0, client=sns)
    assert a.evaluate(rec()) is None
    assert a.evaluate(rec())["delivery"] == "sent-via-sns"
    assert len(sns.calls) == 1 and "CRITICAL" in sns.calls[0]["Subject"]


def test_streak_resets_on_normal():
    a = Alerter("arn:x", consecutive=2, cooldown=0, client=FakeSNS())
    a.evaluate(rec()); a.evaluate(rec("normal"))
    assert a.evaluate(rec()) is None


def test_cooldown_prevents_email_storm():
    sns = FakeSNS()
    a = Alerter("arn:x", consecutive=1, cooldown=300, client=sns)
    for _ in range(5):
        a.evaluate(rec())
    assert len(sns.calls) == 1


def test_sns_failure_does_not_crash():
    a = Alerter("arn:x", consecutive=1, cooldown=0, client=FakeSNS(fail=True))
    assert a.evaluate(rec())["delivery"] == "sns-failed"


def test_without_sns_alert_is_logged_locally():
    a = Alerter("", consecutive=1, cooldown=0)
    assert a.evaluate(rec())["delivery"] == "logged-locally"
