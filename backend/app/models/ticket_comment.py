from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticket_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    author_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    author_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    internal: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="comments")
