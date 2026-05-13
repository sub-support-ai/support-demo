from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.ticket import Ticket
from app.models.user import User


async def create_notification(
    db: AsyncSession,
    *,
    user_id: int,
    event_type: str,
    title: str,
    body: str,
    target_type: str | None = None,
    target_id: int | None = None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        event_type=event_type,
        title=title,
        body=body,
        target_type=target_type,
        target_id=target_id,
    )
    db.add(notification)
    return notification


async def notify_ticket_user(
    db: AsyncSession,
    *,
    ticket: Ticket,
    event_type: str,
    title: str,
    body: str,
) -> Notification:
    return await create_notification(
        db,
        user_id=ticket.user_id,
        event_type=event_type,
        title=title,
        body=body,
        target_type="ticket",
        target_id=ticket.id,
    )


async def notify_users(
    db: AsyncSession,
    *,
    user_ids: Iterable[int],
    event_type: str,
    title: str,
    body: str,
    target_type: str | None = None,
    target_id: int | None = None,
) -> list[Notification]:
    notifications: list[Notification] = []
    for user_id in set(user_ids):
        notifications.append(
            await create_notification(
                db,
                user_id=user_id,
                event_type=event_type,
                title=title,
                body=body,
                target_type=target_type,
                target_id=target_id,
            )
        )
    return notifications


async def notify_active_admins(
    db: AsyncSession,
    *,
    event_type: str,
    title: str,
    body: str,
    target_type: str | None = None,
    target_id: int | None = None,
) -> list[Notification]:
    result = await db.execute(
        select(User.id).where(User.role == "admin", User.is_active.is_(True))
    )
    return await notify_users(
        db,
        user_ids=result.scalars().all(),
        event_type=event_type,
        title=title,
        body=body,
        target_type=target_type,
        target_id=target_id,
    )
