"""Application settings, read from environment variables (or a .env file)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    metrics_source: str = "simulated"      # "simulated" or "real"
    tick_interval: float = 2.0             # seconds between samples
    auto_start_loop: bool = True           # tests switch this off
    api_key: str = "demo-key"
    allowed_origins: str = "http://localhost:5173"

    # ML
    min_train_samples: int = 60            # warm-up samples needed in "real" mode
    retrain_every: int = 300               # retrain on recent normal data every N samples
    history_size: int = 1000               # samples kept in memory

    # Alerting
    alert_cooldown_seconds: int = 60
    alert_consecutive: int = 2             # critical samples in a row before alerting

    # AWS (all optional)
    aws_region: str = "ap-south-1"
    sns_topic_arn: str = ""
    dynamodb_metrics_table: str = ""
    dynamodb_alerts_table: str = ""
    cloudwatch_enabled: bool = False
    cloudwatch_project: str = "cad-monitor"  # CloudWatch dimension value


def get_settings() -> Settings:
    return Settings()
