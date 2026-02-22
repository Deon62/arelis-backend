from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import LawyerSession, User
from ..schemas import LawyerSessionCreate, LawyerSessionOut

router = APIRouter(prefix="/api/sessions", tags=["Lawyer Sessions"])


def _parse_scheduled_at(date_str: str, time_str: str) -> datetime:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    try:
        t = datetime.strptime(time_str.strip(), "%I:%M %p").time()
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid time format. Use e.g. "09:00 AM".')

    return datetime.combine(d, t)


@router.get("", response_model=list[LawyerSessionOut], summary="List my sessions")
def list_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sessions = (
        db.query(LawyerSession)
        .filter(LawyerSession.user_id == current_user.id)
        .order_by(LawyerSession.scheduled_at.desc())
        .all()
    )
    return sessions


@router.post(
    "/book",
    response_model=LawyerSessionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Book a session (pending approval)",
)
def book_session(
    payload: LawyerSessionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scheduled_at = _parse_scheduled_at(payload.date, payload.time)

    session = LawyerSession(
        user_id=current_user.id,
        topic=payload.topic.strip(),
        scheduled_at=scheduled_at,
        notes=(payload.notes.strip() if payload.notes else None),
        status="pending",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session

