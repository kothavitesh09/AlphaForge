import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import get_settings
from app.database.mongo import close_mongo, connect_mongo, get_database
from app.routes import analytics, auth, backfill, coins, dashboard, paper_trade, predictions, signals, ws
from app.services.market_collector import collector_health
from app.workers.scheduler import is_market_collector_running, start_scheduler, stop_scheduler


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await connect_mongo()
    start_scheduler()
    yield
    stop_scheduler()
    await close_mongo()


settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Exception)
async def error_handler(_: Request, exc: Exception):
    logging.exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


async def health_status():
    db = get_database()
    await db.command("ping")
    collector = await collector_health(db)
    return {
        "status": "healthy",
        "mongodb": "connected",
        "collector_running": is_market_collector_running(),
        "active_symbols": len(get_settings().collector_symbols),
        "active_provider": collector["active_provider"],
        "latest_candle_timestamp": collector["latest_candle_timestamp"],
        "collection_latency_ms": collector["collection_latency_ms"],
        "market_data_count": collector["market_data_count"],
        "last_insert_time": collector["last_insert_time"],
    }


@app.get("/health")
async def health():
    return await health_status()


@app.get("/api/health")
async def api_health():
    return await health_status()


app.include_router(auth.router, prefix="/api")
app.include_router(backfill.router, prefix="/api")
app.include_router(coins.router, prefix="/api")
app.include_router(signals.router, prefix="/api")
app.include_router(predictions.router, prefix="/api")
app.include_router(paper_trade.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(ws.router)
