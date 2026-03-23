from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, Notification, NotificationPreference
from app.services.notification_service import get_or_create_prefs

router = APIRouter()


class NotifResponse(BaseModel):
    id: UUID
    type: str
    title: str
    message: str
    is_read: bool
    link: str | None
    created_at: str
    model_config = {"from_attributes": True}


@router.get("/")
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.is_read == False)
    query = query.order_by(Notification.created_at.desc()).limit(limit)
    result = await db.execute(query)
    notifs = result.scalars().all()
    return [
        {
            "id": str(n.id),
            "type": n.type.value,
            "title": n.title,
            "message": n.message,
            "is_read": n.is_read,
            "link": n.link,
            "created_at": n.created_at.isoformat(),
        }
        for n in notifs
    ]


@router.get("/unread-count")
async def unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.is_read == False
        )
    )
    return {"count": result.scalar()}


@router.post("/{notif_id}/read")
async def mark_read(
    notif_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Notification).where(
            Notification.id == notif_id, Notification.user_id == user.id
        ).values(is_read=True)
    )
    await db.commit()
    return {"status": "ok"}


@router.post("/read-all")
async def mark_all_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Notification).where(
            Notification.user_id == user.id, Notification.is_read == False
        ).values(is_read=True)
    )
    await db.commit()
    return {"status": "ok"}


class PrefsUpdate(BaseModel):
    budget_warning_tg: bool = True
    budget_warning_web: bool = True
    subscription_due_tg: bool = True
    subscription_due_web: bool = True
    daily_summary_tg: bool = True
    daily_summary_web: bool = False
    weekly_summary_tg: bool = True
    weekly_summary_web: bool = True
    cooling_ready_tg: bool = True
    cooling_ready_web: bool = True
    daily_summary_time: str = "20:00"
    weekly_summary_time: str = "08:00"


@router.get("/preferences")
async def get_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    prefs = await get_or_create_prefs(user.id, db)
    await db.commit()
    return {
        "budget_warning_tg": prefs.budget_warning_tg,
        "budget_warning_web": prefs.budget_warning_web,
        "subscription_due_tg": prefs.subscription_due_tg,
        "subscription_due_web": prefs.subscription_due_web,
        "daily_summary_tg": prefs.daily_summary_tg,
        "daily_summary_web": prefs.daily_summary_web,
        "weekly_summary_tg": prefs.weekly_summary_tg,
        "weekly_summary_web": prefs.weekly_summary_web,
        "cooling_ready_tg": prefs.cooling_ready_tg,
        "cooling_ready_web": prefs.cooling_ready_web,
        "daily_summary_time": prefs.daily_summary_time or "20:00",
        "weekly_summary_time": prefs.weekly_summary_time or "08:00",
    }


@router.put("/preferences")
async def update_preferences(
    req: PrefsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    prefs = await get_or_create_prefs(user.id, db)
    for key, val in req.dict().items():
        setattr(prefs, key, val)
    await db.commit()
    return {"status": "updated"}
