import asyncio
import os

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.agent import Agent
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
        created = 0
        updated = 0

        for item in DEMO_AGENTS:
            result = await db.execute(
                select(Agent).where(Agent.email == item["email"])
            )
            agent = result.scalar_one_or_none()

            if agent is None:
                agent = Agent(
                    email=item["email"],
                    username=item["username"],
                    hashed_password=hash_password(demo_password),
                    department=item["department"],
                    ai_routing_score=item["ai_routing_score"],
                    is_active=True,
                    active_ticket_count=0,
                )
                db.add(agent)
                created += 1
                continue

            agent.username = item["username"]
            agent.hashed_password = hash_password(demo_password)
            agent.department = item["department"]
            agent.ai_routing_score = item["ai_routing_score"]
            agent.is_active = True
            updated += 1

        await db.commit()

    print(
        f"Demo agents ready: created={created}, updated={updated}. "
        "Password source: DEMO_AGENT_PASSWORD env or documented demo default."
    )


if __name__ == "__main__":
    asyncio.run(seed_demo_agents())
