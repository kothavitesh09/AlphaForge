from fastapi import APIRouter
from app.database.mongo import get_database
from app.services.dashboard import DashboardService


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("")
async def dashboard():
    return await DashboardService(get_database()).overview()
