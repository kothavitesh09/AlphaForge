from fastapi import HTTPException, status
from app.core.security import create_access_token, hash_password, verify_password
from app.repositories.base import MongoRepository


class AuthService:
    def __init__(self, db):
        self.users = MongoRepository(db, "users")

    async def register(self, email: str, password: str, name: str) -> dict:
        existing = await self.users.find_one({"email": email.lower()})
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")
        user = await self.users.insert({"email": email.lower(), "name": name, "password_hash": hash_password(password), "telegram_chat_id": None})
        user.pop("password_hash", None)
        return {"access_token": create_access_token(user["id"]), "user": user}

    async def login(self, email: str, password: str) -> dict:
        user = await self.users.find_one({"email": email.lower()})
        if not user or not verify_password(password, user["password_hash"]):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        user.pop("password_hash", None)
        return {"access_token": create_access_token(user["id"]), "user": user}

    async def profile(self, user_id: str) -> dict:
        user = await self.users.find_one({"id": user_id})
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        user.pop("password_hash", None)
        return user
