"""FastAPI application: REST API + (optionally) the built React dashboard."""
import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from .collector import SCENARIOS
from .config import Settings, get_settings
from .engine import MonitoringEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("main")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class SimulateRequest(BaseModel):
    scenario: Literal["cpu_spike", "memory_leak", "disk_fill", "network_flood", "full_failure"]


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"
        return resp


def create_app(settings: Optional[Settings] = None, engine: Optional[MonitoringEngine] = None) -> FastAPI:
    settings = settings or get_settings()
    engine = engine or MonitoringEngine(settings)

    async def monitor_loop():
        while True:
            try:
                await asyncio.to_thread(engine.step)
                engine.last_error = None
            except Exception as exc:  # keep monitoring alive no matter what
                engine.last_error = str(exc)
                logger.exception("monitoring cycle failed")
            await asyncio.sleep(settings.tick_interval)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(monitor_loop()) if settings.auto_start_loop else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="AI Cloud Monitor", version="1.0.0", lifespan=lifespan)
    app.state.engine = engine
    app.add_middleware(SecurityHeaders)
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.allowed_origins.split(",") if o.strip()],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-API-Key"])

    def require_key(x_api_key: str = Header(default="")):
        if not hmac.compare_digest(x_api_key.encode(), settings.api_key.encode()):
            raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "model_trained": engine.detector.is_trained, "last_error": engine.last_error}

    @app.get("/api/overview")
    def overview(history: int = Query(120, ge=10, le=1000)):
        return engine.overview(history)

    @app.get("/api/anomalies")
    def anomalies(limit: int = Query(50, ge=1, le=200)):
        return engine.store.recent_anomalies(limit)

    @app.get("/api/alerts")
    def alerts(limit: int = Query(50, ge=1, le=200)):
        return engine.store.recent_alerts(limit)

    @app.post("/api/simulate", dependencies=[Depends(require_key)])
    def simulate(req: SimulateRequest):
        engine.collector.start_scenario(req.scenario)
        return {"started": req.scenario, "description": SCENARIOS[req.scenario]}

    @app.post("/api/simulate/stop", dependencies=[Depends(require_key)])
    def stop():
        engine.collector.stop_scenario()
        return {"stopped": True}

    @app.post("/api/retrain", dependencies=[Depends(require_key)])
    def retrain():
        try:
            n = engine.retrain()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"retrained_on": n, "version": engine.detector.version}

    # Serve the built dashboard (single-server deployment on EC2)
    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(status_code=404)
            f = (FRONTEND_DIST / path).resolve()
            if path and f.is_file() and FRONTEND_DIST in f.parents:
                return FileResponse(f)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
