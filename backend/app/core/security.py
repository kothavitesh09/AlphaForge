from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.core.config import get_settings


password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_context.verify(password, hashed_password)


def create_access_token(subject: str) -> str:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode({"sub": subject, "exp": expires}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str = Depends(oauth2_scheme)) -> str:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        subject = payload.get("sub")
        if not subject:
            raise JWTError()
        return subject
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token") from exc
