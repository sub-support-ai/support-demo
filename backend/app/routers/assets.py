"""
Router: /api/v1/assets

CMDB-lite — управление активами (ноутбуки, принтеры, сервисы и т.д.).

Права доступа:
  GET  /assets/           — любой авторизованный (агенты ищут активы при создании тикета)
  GET  /assets/search     — любой авторизованный (autocomplete)
  GET  /assets/{id}       — любой авторизованный
  POST /assets/           — только admin
  PATCH /assets/{id}      — только admin
  DELETE /assets/{id}     — только admin; блокируется если есть тикеты с этим активом
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.asset import ASSET_STATUSES, ASSET_TYPES, Asset
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.asset import AssetCreate, AssetRead, AssetUpdate

router = APIRouter(prefix="/assets", tags=["assets"])


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_asset_or_404(asset_id: int, db: AsyncSession) -> Asset:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


def _validate_type(asset_type: str) -> None:
    if asset_type not in ASSET_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid asset_type '{asset_type}'. "
            f"Allowed: {sorted(ASSET_TYPES)}",
        )


def _validate_status(asset_status: str) -> None:
    if asset_status not in ASSET_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{asset_status}'. "
            f"Allowed: {sorted(ASSET_STATUSES)}",
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/search", response_model=list[AssetRead])
async def search_assets(
    q: str = Query(..., min_length=2, max_length=100, description="Поиск по имени или серийнику"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[Asset]:
    """Быстрый поиск для autocomplete в форме тикета."""
    pattern = f"%{q}%"
    result = await db.execute(
        select(Asset)
        .where(
            or_(
                Asset.name.ilike(pattern),
                Asset.serial_number.ilike(pattern),
            )
        )
        .order_by(Asset.name.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/", response_model=list[AssetRead])
async def list_assets(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    asset_type: str | None = Query(None, description="Фильтр по типу"),
    asset_status: str | None = Query(None, alias="status", description="Фильтр по статусу"),
    office: str | None = Query(None, description="Фильтр по офису"),
    owner_user_id: int | None = Query(None, description="Фильтр по владельцу"),
    search: str | None = Query(None, min_length=2, description="Поиск по имени / серийнику"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[Asset]:
    """Список активов с фильтрами. Доступен всем авторизованным пользователям."""
    if asset_type is not None:
        _validate_type(asset_type)
    if asset_status is not None:
        _validate_status(asset_status)

    q = select(Asset)
    if asset_type:
        q = q.where(Asset.asset_type == asset_type)
    if asset_status:
        q = q.where(Asset.status == asset_status)
    if office:
        q = q.where(Asset.office.ilike(f"%{office}%"))
    if owner_user_id is not None:
        q = q.where(Asset.owner_user_id == owner_user_id)
    if search:
        pattern = f"%{search}%"
        q = q.where(
            or_(
                Asset.name.ilike(pattern),
                Asset.serial_number.ilike(pattern),
            )
        )

    q = q.order_by(Asset.name.asc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/{asset_id}", response_model=AssetRead)
async def get_asset(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Asset:
    return await _get_asset_or_404(asset_id, db)


@router.post("/", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
async def create_asset(
    payload: AssetCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role("admin")),
) -> Asset:
    """Создать актив. Только admin."""
    _validate_type(payload.asset_type)
    _validate_status(payload.status)

    # Проверяем, существует ли владелец
    if payload.owner_user_id is not None:
        owner = await db.get(User, payload.owner_user_id)
        if owner is None:
            raise HTTPException(status_code=422, detail="owner_user_id: user not found")

    asset = Asset(**payload.model_dump())
    db.add(asset)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="serial_number already exists for another asset",
        ) from None
    await db.commit()
    await db.refresh(asset)
    return asset


@router.patch("/{asset_id}", response_model=AssetRead)
async def update_asset(
    asset_id: int,
    payload: AssetUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role("admin")),
) -> Asset:
    """Обновить поля актива. Только admin."""
    asset = await _get_asset_or_404(asset_id, db)

    update_data = payload.model_dump(exclude_unset=True)

    if "asset_type" in update_data and update_data["asset_type"] is not None:
        _validate_type(update_data["asset_type"])
    if "status" in update_data and update_data["status"] is not None:
        _validate_status(update_data["status"])
    if "owner_user_id" in update_data and update_data["owner_user_id"] is not None:
        owner = await db.get(User, update_data["owner_user_id"])
        if owner is None:
            raise HTTPException(status_code=422, detail="owner_user_id: user not found")

    for field, value in update_data.items():
        setattr(asset, field, value)

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="serial_number already exists for another asset",
        ) from None
    await db.commit()
    await db.refresh(asset)
    return asset


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role("admin")),
) -> None:
    """Удалить актив. Только admin.

    Блокируется (409) если на актив ссылаются тикеты — сначала нужно
    обновить или закрыть эти тикеты. Это предотвращает потерю истории.
    """
    asset = await _get_asset_or_404(asset_id, db)

    ticket_count_result = await db.execute(
        select(func.count()).select_from(Ticket).where(Ticket.asset_id == asset_id)
    )
    ticket_count = ticket_count_result.scalar_one()
    if ticket_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete asset: {ticket_count} ticket(s) reference it. "
            "Update or close those tickets first.",
        )

    await db.delete(asset)
    await db.commit()
