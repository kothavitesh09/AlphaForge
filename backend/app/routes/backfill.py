from fastapi import APIRouter
from app.database.mongo import get_database
from app.services.backfill import BackfillService, backfill_manager


router = APIRouter(prefix="/backfill", tags=["Backfill"])


@router.post("/start")
async def start_backfill(payload: dict | None = None):
    return backfill_manager.start(get_database(), payload or {})


@router.get("/status")
async def backfill_status():
    status = await BackfillService(get_database()).status()
    return {**status, "task_running": backfill_manager.running(), "last_error": backfill_manager.last_error, "last_result": backfill_manager.last_result}
