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
    {
        "email": "procurement.agent@example.com",
        "username": "procurement_agent",
        "department": "procurement",
        "ai_routing_score": 0.88,
    },
    {
        "email": "security.agent@example.com",
        "username": "security_agent",
        "department": "security",
        "ai_routing_score": 0.91,
    },
    {
        "email": "facilities.agent@example.com",
        "username": "facilities_agent",
        "department": "facilities",
        "ai_routing_score": 0.87,
    },
    {
        "email": "documents.agent@example.com",
        "username": "documents_agent",
        "department": "documents",
        "ai_routing_score": 0.89,
    },
]

DEFAULT_DEMO_PASSWORD = "DemoPass123!"


async def seed_demo_agents() -> None:
    demo_password = os.getenv("DEMO_AGENT_PASSWORD", DEFAULT_DEMO_PASSWORD)

    async with AsyncSessionLocal() as db:
        agents_created = 0
        agents_updated = 0
        users_created = 0
        users_updated = 0

        for item in DEMO_AGENTS:
            password_hash = hash_password(demo_password)

            user_result = await db.execute(
                select(User).where(
                    (User.email == item["email"]) | (User.username == item["username"])
                )
            )
            user = user_result.scalar_one_or_none()
            if user is None:
                user = User(
                    email=item["email"],
                    username=item["username"],
                    hashed_password=password_hash,
                    role="agent",
                    is_active=True,
                )
                db.add(user)
                users_created += 1
            else:
                user.email = item["email"]
                user.username = item["username"]
                user.hashed_password = password_hash
                user.role = "agent"
                user.is_active = True
                users_updated += 1
            await db.flush()

            result = await db.execute(
                select(Agent).where(Agent.email == item["email"])
            )
            agent = result.scalar_one_or_none()

            if agent is None:
                agent = Agent(
                    user_id=user.id,
                    email=item["email"],
                    username=item["username"],
                    hashed_password=password_hash,
                    department=item["department"],
                    ai_routing_score=item["ai_routing_score"],
                    is_active=True,
                    active_ticket_count=0,
                )
                db.add(agent)
                agents_created += 1
            else:
                agent.user_id = user.id
                agent.username = item["username"]
                agent.hashed_password = password_hash
                agent.department = item["department"]
                agent.ai_routing_score = item["ai_routing_score"]
                agent.is_active = True
                agents_updated += 1

        await db.commit()

    print(
        "Demo agents ready: "
        f"agents_created={agents_created}, agents_updated={agents_updated}, "
        f"users_created={users_created}, users_updated={users_updated}. "
        "Password source: DEMO_AGENT_PASSWORD env or documented demo default."
    )


if __name__ == "__main__":
    asyncio.run(seed_demo_agents())
