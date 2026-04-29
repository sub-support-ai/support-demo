"""
Общие FastAPI-зависимости для всех роутеров.

get_current_user — разбирает JWT из заголовка Authorization: Bearer <token>,
                    возвращает ORM-объект User. 401 если токен невалиден/истёк
                    или пользователь заблокирован.

require_role("admin") — гейт по роли, оборачивает get_current_user.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Токен недействителен или истёк",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise credentials_error

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise credentials_error

    return user


def require_role(required_role: str):
    """Зависимость для гейта по роли. Использование: Depends(require_role("admin"))."""
    async def role_dependency(current_user: User = Depends(get_current_user)) -> User:
        if getattr(current_user, "role", None) != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user
    return role_dependency
