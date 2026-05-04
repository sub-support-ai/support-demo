import asyncio
import os

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.agent import Agent
from app.models.user import User
from app.security import hash_password


DEMO_AGENTS = [
    {
        "email": "it.agent@example.com",
        "username": "it_agent",
        "department": "IT",
        "ai_routing_score": 0.95,
    },
    {
        "email": "hr.agent@example.com",
        "username": "hr_agent",
        "department": "HR",
        "ai_routing_score": 0.90,
    },
    {
        "email": "finance.agent@example.com",
        "username": "finance_agent",
        "department": "finance",
        "ai_routing_score": 0.92,
    },
]

DEFAULT_DEMO_PASSWORD = "DemoPass123!"


async def seed_demo_agents() -> None:
    demo_password = os.getenv("DEMO_AGENT_PASSWORD", DEFAULT_DEMO_PASSWORD)

    async with AsyncSessionLocal() as db:
        created_agents = 0
        updated_agents = 0
        created_users = 0
        updated_users = 0

        for item in DEMO_AGENTS:
            password_hash = hash_password(demo_password)
            result = await db.execute(
                select(Agent).where(Agent.email == item["email"])
            )
            agent = result.scalar_one_or_none()

            if agent is None:
                agent = Agent(
                    email=item["email"],
                    username=item["username"],
                    hashed_password=password_hash,
                    department=item["department"],
                    ai_routing_score=item["ai_routing_score"],
                    is_active=True,
                    active_ticket_count=0,
                )
                db.add(agent)
                created_agents += 1
            else:
                agent.username = item["username"]
                agent.hashed_password = password_hash
                agent.department = item["department"]
                agent.ai_routing_score = item["ai_routing_score"]
                agent.is_active = True
                updated_agents += 1

            result = await db.execute(
                select(User).where(
                    (User.email == item["email"])
                    | (User.username == item["username"])
                )
            )
            users = list(result.scalars().all())
            if len(users) > 1:
                raise RuntimeError(
                    "Cannot seed demo agent user because email and username "
                    f"belong to different users: {item['email']}, {item['username']}"
                )

            user = users[0] if users else None
            if user is None:
                user = User(
                    email=item["email"],
                    username=item["username"],
                    hashed_password=password_hash,
                    role="agent",
                    is_active=True,
                )
                db.add(user)
                created_users += 1
            else:
                user.email = item["email"]
                user.username = item["username"]
                user.hashed_password = password_hash
                user.role = "agent"
                user.is_active = True
                updated_users += 1

        await db.commit()

    print(
        "Demo agents ready: "
        f"agents created={created_agents}, agents updated={updated_agents}, "
        f"users created={created_users}, users updated={updated_users}. "
        "Password source: DEMO_AGENT_PASSWORD env or documented demo default."
    )


if __name__ == "__main__":
    asyncio.run(seed_demo_agents())
