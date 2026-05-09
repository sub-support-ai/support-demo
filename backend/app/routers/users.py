from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.schemas.user import UserActiveUpdate, UserCreate, UserRead, UserRoleUpdate
from app.security import hash_password
from app.services.audit import log_event

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/", response_model=list[UserRead])
async def list_users(
    skip: int = Query(default=0, ge=0),
    # limit ограничен 200 — без этого можно запросить миллион записей
    # и положить сервер
    limit: int = Query(default=100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    result = await db.execute(select(User).offset(skip).limit(limit))
    return result.scalars().all()


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Пользователь видит только себя, админ — кого угодно
    if current_user.id != user_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


@router.post(
    "/",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать пользователя (admin-only)",
    description="Для самостоятельной регистрации используйте POST /auth/register.",
)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    # Проверка уникальности email
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Проверка уникальности username
    existing = await db.execute(select(User).where(User.username == payload.username))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )

    user = User(
        email=payload.email,
        username=payload.username,
        hashed_password=hash_password(payload.password),  # bcrypt
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.patch(
    "/{user_id}/role",
    response_model=UserRead,
    summary="Сменить роль пользователя (admin-only)",
    description=(
        "Меняет роль user/agent/admin. Защищён от двух классов ошибок:\n"
        "1) self-demotion: админ не может понизить сам себя (любое\n"
        "   действие, переводящее текущего пользователя в роль ниже\n"
        "   admin, отвергается с 409). Понижать админа должен другой\n"
        "   админ — это барьер от случайного клика и компрометации.\n"
        "2) последний админ: понижение приводит к 409, если больше\n"
        "   ни одной admin-роли в системе не останется. Без этого\n"
        "   возможен lock-out (некому раздать роли обратно).\n\n"
        "Записывает действие в audit_log с переходом from→to."
    ),
)
async def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    if user_id == admin.id and payload.role != "admin":
        # См. docstring: self-demotion запрещён, чтобы исключить
        # компрометированную сессию или случайный клик.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Admin cannot demote themselves; ask another admin",
        )

    # Защита от race на "последнем админе": до любых проверок и записей
    # блокируем ВСЕ admin-строки в детерминированном порядке по id.
    # Один и тот же порядок во всех конкурентных вызовах исключает
    # deadlock между двумя админами, демоутящими друг друга. Затем
    # блокируем target — если он admin, лок уже взят (re-entrant в той
    # же транзакции). Только после этого считываем актуальное состояние.
    await db.execute(
        select(User)
        .where(User.role == "admin")
        .order_by(User.id)
        .with_for_update()
    )
    target = (
        await db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    old_role = target.role
    if old_role == payload.role:
        # Идемпотентность: запрос ничего не меняет — отдаём 200 без
        # записи в audit_log (чтобы не засорять журнал no-op'ами).
        return target

    if old_role == "admin" and payload.role != "admin":
        # Под локом считаем количество админов. После лока счётчик
        # стабилен до конца транзакции.
        admin_count = await db.scalar(
            select(func.count()).select_from(User).where(User.role == "admin")
        )
        if admin_count is None or admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot demote the last remaining admin",
            )

    target.role = payload.role
    await log_event(
        db,
        action="user.role_change",
        user_id=admin.id,
        target_type="user",
        target_id=target.id,
        request=request,
        details={"from": old_role, "to": payload.role},
    )
    await db.flush()
    await db.refresh(target)
    return target


@router.patch(
    "/{user_id}/active",
    response_model=UserRead,
    summary="Заблокировать / разблокировать пользователя (admin-only)",
    description=(
        "Меняет is_active. Активный пользователь отключается немедленно: "
        "get_current_user проверяет is_active при каждом запросе, поэтому "
        "текущий токен начинает возвращать 401 сразу после деактивации.\n\n"
        "Защиты:\n"
        "1) Нельзя деактивировать самого себя.\n"
        "2) Нельзя деактивировать последнего активного admin'а — иначе "
        "   система теряет возможность управления.\n"
        "Действие записывается в audit_log."
    ),
)
async def update_user_active(
    user_id: int,
    payload: UserActiveUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    if user_id == admin.id and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Admin cannot deactivate themselves",
        )

    # Блокируем target сразу — FOR UPDATE гарантирует, что параллельный
    # запрос увидит наш is_active после commit, а не читает stale-значение.
    target = (
        await db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if target.is_active == payload.is_active:
        # Идемпотентность: состояние уже такое — отдаём 200 без записи в лог.
        return target

    if not payload.is_active and target.role == "admin":
        # Защита от lock-out: не позволяем деактивировать единственного
        # активного admin'а. Блокировка всех admin-строк (как в role_change)
        # здесь избыточна — достаточно подсчитать активных admin'ов под
        # уже взятым локом на target.
        active_admin_count = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.is_active.is_(True))
        )
        if active_admin_count is not None and active_admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot deactivate the last active admin",
            )

    target.is_active = payload.is_active
    action = "user.deactivate" if not payload.is_active else "user.activate"
    await log_event(
        db,
        action=action,
        user_id=admin.id,
        target_type="user",
        target_id=target.id,
        request=request,
        details={"is_active": payload.is_active},
    )
    await db.flush()
    await db.refresh(target)
    return target
