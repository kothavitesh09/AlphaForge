from fastapi import APIRouter

from app.database.mongo import get_database
from app.repositories.base import serialize
from app.services.performance_engine import PerformanceEngine


router = APIRouter(tags=["Performance"])


@router.get("/performance")
async def performance_dashboard():
    return await PerformanceEngine(get_database()).dashboard()


@router.post("/performance/refresh")
async def refresh_performance():
    return serialize(await PerformanceEngine(get_database()).refresh())


@router.post("/performance/lifecycle-weights/refresh")
async def refresh_lifecycle_weights():
    return serialize(await PerformanceEngine(get_database()).update_lifecycle_model_weights())
