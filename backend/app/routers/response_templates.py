from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.response_template import ResponseTemplate
from app.models.user import User
from app.schemas.response_template import ResponseTemplateCreate, ResponseTemplateRead
from app.services.agents import get_active_agent_for_user
from app.services.audit import log_event

router = APIRouter(prefix="/response-templates", tags=["response-templates"])


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


@router.get("/", response_model=list[ResponseTemplateRead])
async def list_response_templates(
    department: str | None = Query(default=None),
    request_type: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in {"agent", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    query = select(ResponseTemplate)

    if active_only:
        query = query.where(ResponseTemplate.is_active.is_(True))

    if current_user.role == "agent":
        agent = await get_active_agent_for_user(db, current_user)
        if agent is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Agent profile not found",
            )
        department = agent.department

    if department:
        query = query.where(
            or_(
                ResponseTemplate.department == department,
                ResponseTemplate.department.is_(None),
            )
        )
    if request_type:
        query = query.where(
            or_(
                ResponseTemplate.request_type == request_type,
                ResponseTemplate.request_type.is_(None),
            )
        )

    query = query.order_by(
        ResponseTemplate.department.asc(),
        ResponseTemplate.request_type.asc(),
        ResponseTemplate.title.asc(),
    )
    result = await db.execute(query)
    return result.scalars().all()


@router.post(
    "/",
    response_model=ResponseTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_response_template(
    payload: ResponseTemplateCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    template = ResponseTemplate(
        department=payload.department,
        request_type=_clean_optional_text(payload.request_type),
        title=payload.title.strip(),
        body=payload.body.strip(),
        is_active=payload.is_active,
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)

    await log_event(
        db,
        action="response_template.create",
        user_id=admin.id,
        target_type="response_template",
        target_id=template.id,
        request=request,
        details={
            "department": template.department,
            "request_type": template.request_type,
        },
    )
    return template
