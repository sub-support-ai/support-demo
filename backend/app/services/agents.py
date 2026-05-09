from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.user import User


async def get_active_agent_for_user(
    db: AsyncSession,
    current_user: User,
) -> Agent | None:
    result = await db.execute(
        select(Agent)
        .where(Agent.is_active.is_(True))
        .where(
            or_(
                Agent.user_id == current_user.id,
                Agent.email == current_user.email,
                Agent.username == current_user.username,
            )
        )
        .order_by(
            case(
                (Agent.user_id == current_user.id, 0),
                else_=1,
            ).asc()
        )
        .limit(1)
    )
    return result.scalar_one_or_none()
