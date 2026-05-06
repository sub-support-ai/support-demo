from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.user import User


async def get_active_agent_for_user(
    db: AsyncSession,
    current_user: User,
) -> Agent | None:
    result = await db.execute(
        select(Agent)
        .where(Agent.user_id == current_user.id)
        .where(Agent.is_active.is_(True))
        .limit(1)
    )
    agent = result.scalar_one_or_none()
    if agent is not None:
        return agent

    result = await db.execute(
        select(Agent)
        .where((Agent.email == current_user.email) | (Agent.username == current_user.username))
        .where(Agent.is_active.is_(True))
        .limit(1)
    )
    return result.scalar_one_or_none()
