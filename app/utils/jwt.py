from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import HTTPException, status
from app.config import get_settings

settings = get_settings()


def create_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(
        minutes=settings.jwt_expire_minutes
    )
    payload = {
        "sub": user_id,
        "exp": expire
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )


def verify_token(token: str) -> str:
    """
    Returns user_id if token is valid.
    Raises 401 if invalid or expired.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        return user_id
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )