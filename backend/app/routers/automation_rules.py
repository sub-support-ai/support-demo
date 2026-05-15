"""
CRUD эндпоинты для управления правилами автоматизации.

Доступ: только role=admin.

GET    /automation-rules/          — список всех правил
POST   /automation-rules/          — создать правило
GET    /automation-rules/{id}      — получить одно правило
PATCH  /automation-rules/{id}      — обновить правило
DELETE /automation-rules/{id}      — удалить правило
PATCH  /automation-rules/{id}/toggle — включить / выключить
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_role
from app.models.automation_rule import AutomationRule
from app.schemas.automation_rule import (
    AutomationRuleCreate,
    AutomationRuleRead,
    AutomationRuleUpdate,
)

router = APIRouter(prefix="/automation-rules", tags=["automation"])


async def _get_rule_or_404(rule_id: int, db: AsyncSession) -> AutomationRule:
    result = await db.execute(
        select(AutomationRule).where(AutomationRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


@router.get("/", response_model=list[AutomationRuleRead], summary="Список правил автоматизации")
async def list_rules(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_role("admin")),
):
    result = await db.execute(
        select(AutomationRule).order_by(AutomationRule.priority.asc(), AutomationRule.id.asc())
    )
    return result.scalars().all()


@router.post(
    "/",
    response_model=AutomationRuleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать правило автоматизации",
)
async def create_rule(
    payload: AutomationRuleCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_role("admin")),
):
    rule = AutomationRule(
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
        priority=payload.priority,
        trigger=payload.trigger,
        conditions=[c.model_dump() for c in payload.conditions],
        actions=[a.model_dump(exclude_none=True) for a in payload.actions],
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.get(
    "/{rule_id}",
    response_model=AutomationRuleRead,
    summary="Получить правило автоматизации",
)
async def get_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_role("admin")),
):
    return await _get_rule_or_404(rule_id, db)


@router.patch(
    "/{rule_id}",
    response_model=AutomationRuleRead,
    summary="Обновить правило автоматизации",
)
async def update_rule(
    rule_id: int,
    payload: AutomationRuleUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_role("admin")),
):
    rule = await _get_rule_or_404(rule_id, db)

    if payload.name is not None:
        rule.name = payload.name
    if payload.description is not None:
        rule.description = payload.description
    if payload.is_active is not None:
        rule.is_active = payload.is_active
    if payload.priority is not None:
        rule.priority = payload.priority
    if payload.trigger is not None:
        rule.trigger = payload.trigger
    if payload.conditions is not None:
        rule.conditions = [c.model_dump() for c in payload.conditions]
    if payload.actions is not None:
        rule.actions = [a.model_dump(exclude_none=True) for a in payload.actions]

    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch(
    "/{rule_id}/toggle",
    response_model=AutomationRuleRead,
    summary="Включить / выключить правило",
)
async def toggle_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_role("admin")),
):
    rule = await _get_rule_or_404(rule_id, db)
    rule.is_active = not rule.is_active
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить правило автоматизации",
)
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_role("admin")),
):
    rule = await _get_rule_or_404(rule_id, db)
    await db.delete(rule)
    await db.commit()
