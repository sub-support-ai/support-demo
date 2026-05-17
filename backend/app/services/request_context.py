from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.user import User

OFFICE_OPTIONS = ("Главный офис", "Склад", "Удаленно")
AFFECTED_ITEM_OPTIONS = (
    "Рабочее место",
    "Ноутбук",
    "Принтер/МФУ",
    "VPN",
    "1C",
    "Почта",
)

_OFFICE_EMAIL_HINTS = {
    "Главный офис": ("hq", "main", "office", "msk", "moscow"),
    "Склад": ("warehouse", "sklad", "store"),
    "Удаленно": ("remote", "home"),
}


def infer_office_from_email(email: str) -> str | None:
    normalized = email.lower()
    for office, hints in _OFFICE_EMAIL_HINTS.items():
        if any(hint in normalized for hint in hints):
            return office
    return None


def _asset_display_name(asset: Asset) -> str:
    if asset.serial_number:
        return f"{asset.name} ({asset.serial_number})"
    return asset.name


def _select_primary_asset(assets: list[Asset]) -> Asset | None:
    preferred_types = {"laptop": 0, "desktop": 1, "phone": 2}
    active_assets = [asset for asset in assets if asset.status == "active"]
    candidates = active_assets or assets
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda asset: (preferred_types.get(asset.asset_type, 10), asset.name.casefold()),
    )[0]


async def get_user_assets(db: AsyncSession, user: User) -> list[Asset]:
    result = await db.execute(
        select(Asset)
        .where(Asset.owner_user_id == user.id)
        .order_by(
            Asset.status.asc(),
            Asset.asset_type.asc(),
            Asset.name.asc(),
        )
    )
    return list(result.scalars().all())


async def build_request_context(db: AsyncSession, user: User) -> dict[str, object]:
    assets = await get_user_assets(db, user)
    primary_asset = _select_primary_asset(assets)
    office = (
        primary_asset.office
        if primary_asset and primary_asset.office
        else infer_office_from_email(user.email)
    )
    asset_options = [_asset_display_name(asset) for asset in assets if asset.status == "active"]
    office_options = list(dict.fromkeys([*([office] if office else []), *OFFICE_OPTIONS]))
    affected_item_options = list(dict.fromkeys([*asset_options, *AFFECTED_ITEM_OPTIONS]))
    return {
        "requester_name": user.username,
        "requester_email": user.email,
        "office": office,
        "office_source": (
            "asset" if primary_asset and primary_asset.office else ("email" if office else None)
        ),
        "office_options": office_options,
        "affected_item_options": affected_item_options,
        "primary_asset": primary_asset,
        "assets": assets,
    }
