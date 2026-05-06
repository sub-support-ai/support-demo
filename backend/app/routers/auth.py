from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.rate_limit import rate_limit
from app.schemas.auth import TokenResponse, UserMe
from app.schemas.user import UserCreate
from app.security import create_access_token, hash_password, verify_password
from app.services.agents import get_active_agent_for_user
from app.services.audit import log_event
from app.services.request_context import build_request_context

router = APIRouter(prefix="/auth", tags=["auth"])


# ── POST /auth/login — войти и получить токен ─────────────────────────────────
# Лимит: 5 попыток входа с одного IP в минуту. Подбор пароля за этим лимитом
# в среднем ~7200 попыток в сутки — при нормальном пароле это десятилетия
# перебора. Настоящие пользователи попадают в лимит разве что случайно
# (залип Caps Lock) и через минуту могут снова.
@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit(max_calls=5, window_seconds=60))],
)
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),  # стандартная форма: username + password
    db: AsyncSession = Depends(get_db),
):
    # Ищем пользователя по username
    result = await db.execute(select(User).where(User.username == form.username))
    user = result.scalar_one_or_none()

    # Если не нашли или пароль неверный — одна и та же ошибка
    # (не говорим что именно неверно — безопаснее)
    if not user or not verify_password(form.password, user.hashed_password):
        # Неудачный логин — главный сигнал для аудита (брутфорс-попытки).
        # Важный нюанс: get_db() делает rollback при HTTPException, а это
        # откатило бы и наш audit_log. Поэтому коммитим ЯВНО перед raise —
        # последующий rollback откатит уже пустую транзакцию.
        await log_event(
            db,
            action="login.failure",
            user_id=user.id if user else None,   # None если username вообще не существует
            request=request,
            details={"username": form.username},   # запоминаем, какой username пытались подобрать
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )

    if not user.is_active:
        # Попытка входа на заблокированный аккаунт — важный сигнал:
        # либо сам пользователь не знает, что его забанили (тогда можно
        # объяснить в саппорте), либо кто-то целенаправленно ломится
        # в отключённый аккаунт. В обоих случаях нужно видеть попытку.
        # Тот же паттерн, что и на login.failure: commit ПЕРЕД raise,
        # потому что get_db() откатит транзакцию на HTTPException.
        await log_event(
            db,
            action="login.blocked",
            user_id=user.id,
            request=request,
            details={"username": form.username},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Аккаунт заблокирован",
        )

    # Удачный логин — audit уйдёт штатно с общим commit в get_db.
    await log_event(db, action="login.success", user_id=user.id, request=request)

    # Создаём токен и возвращаем
    token = create_access_token(user_id=user.id, role=user.role)
    return TokenResponse(access_token=token)


# ── POST /auth/register — регистрация + сразу токен ───────────────────────────
# Лимит: 3 регистрации с одного IP в минуту. Защита от спам-ботов, которые
# пытаются забить базу фейковыми аккаунтами. Легальный пользователь
# регистрируется один раз — лимит его никогда не коснётся.
@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(max_calls=3, window_seconds=60))],
)
async def register(
    payload: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Создаёт нового пользователя и сразу выдаёт access token,
    чтобы не делать лишний POST /auth/login после регистрации.
    """
    # Уникальность email
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Уникальность username
    existing = await db.execute(select(User).where(User.username == payload.username))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )

    # Bootstrap-admin: если email в .env совпадает — сразу даём админскую роль.
    # Нужен для решения "курица-яйцо": без этого первого админа негде взять,
    # т.к. POST /users/ тоже требует admin-токена (см. app/config.py → BOOTSTRAP_ADMIN_EMAIL).
    settings = get_settings()
    bootstrap_email = settings.BOOTSTRAP_ADMIN_EMAIL
    is_bootstrap_admin = (
        bootstrap_email is not None
        and payload.email.lower() == bootstrap_email.lower()
    )
    role = "admin" if is_bootstrap_admin else "user"

    user = User(
        email=payload.email,
        username=payload.username,
        hashed_password=hash_password(payload.password),
        role=role,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    await log_event(
        db,
        action="user.register",
        user_id=user.id,
        request=request,
        details={"role": role},   # видно будет и bootstrap-admin'а, и обычных
    )

    token = create_access_token(user_id=user.id, role=user.role)
    return TokenResponse(access_token=token)


# ── GET /auth/me — кто я? ─────────────────────────────────────────────────────
@router.get("/me", response_model=UserMe)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Вернуть данные текущего авторизованного пользователя."""
    agent = None
    if current_user.role == "agent":
        agent = await get_active_agent_for_user(db, current_user)

    return UserMe(
        id=current_user.id,
        email=current_user.email,
        username=current_user.username,
        role=current_user.role,
        is_active=current_user.is_active,
        agent_id=agent.id if agent else None,
        agent_department=agent.department if agent else None,
        request_context=build_request_context(current_user),
    )
