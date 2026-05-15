from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.ticket import Ticket
    from app.models.user import User

# Допустимые типы активов (строки, не DB-enum — как и статусы тикетов)
ASSET_TYPES = {
    "laptop",
    "desktop",
    "monitor",
    "printer",
    "phone",
    "network_device",
    "server",
    "peripheral",
    "software",
    "service",
    "other",
}

# Допустимые статусы актива
ASSET_STATUSES = {"active", "in_repair", "decommissioned", "lost"}


class Asset(Base):
    """
    CMDB-lite: инвентарный объект (ноутбук, принтер, сервис и т.д.).

    Тикет может ссылаться на Asset через Ticket.asset_id.
    Поле Ticket.affected_item остаётся как fallback для свободного текста
    (например, если объект ещё не внесён в CMDB).
    """

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Тип актива: строка из ASSET_TYPES
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Отображаемое имя, например «MacBook Pro Даниил» или «HP LaserJet 101»
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Серийный номер — уникальный среди непустых значений (NULL разрешён)
    # Уникальность гарантирует partial index в миграции:
    #   CREATE UNIQUE INDEX uq_assets_serial_notnull
    #   ON assets (serial_number) WHERE serial_number IS NOT NULL
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Владелец — пользователь системы; NULL = «общий» или «неизвестен»
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Физическое расположение / офис
    office: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Текущий статус: active | in_repair | decommissioned | lost
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="active",
        server_default="active",
        index=True,
    )

    # Свободный комментарий (история, инвентарный номер, ссылка)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    owner: Mapped["User | None"] = relationship("User", back_populates="assets")

    # Тикеты, где этот актив указан как затронутый объект
    tickets: Mapped[list["Ticket"]] = relationship("Ticket", back_populates="asset")
