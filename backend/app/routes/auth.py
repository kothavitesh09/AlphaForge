from fastapi import APIRouter, Depends
from app.core.security import decode_token
from app.database.mongo import get_database
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.services.auth import AuthService


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse)
async def register(payload: RegisterRequest):
    return await AuthService(get_database()).register(payload.email, payload.password, payload.name)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    return await AuthService(get_database()).login(payload.email, payload.password)


@router.get("/profile")
async def profile(user_id: str = Depends(decode_token)):
    return await AuthService(get_database()).profile(user_id)
