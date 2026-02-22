import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import BillingProfile, BillingTransaction, User
from ..schemas import BillingTransactionOut, MpesaOut, MpesaUpdate

router = APIRouter(prefix="/api/billing", tags=["Billing"])


def _normalize_msisdn(raw: str) -> str:
    s = re.sub(r"\s+", "", (raw or "")).replace("+", "")
    s = re.sub(r"[^\d]", "", s)

    if not s:
        raise HTTPException(status_code=400, detail="M-Pesa number is required")

    # Accept 07XXXXXXXX, 7XXXXXXXX, 2547XXXXXXXX
    if s.startswith("0") and len(s) in (10,):
        s = "254" + s[1:]
    elif len(s) == 9 and s.startswith("7"):
        s = "254" + s

    if not (len(s) == 12 and s.startswith("2547")):
        raise HTTPException(status_code=400, detail="Enter a valid Safaricom number (e.g. 0712 345 678)")

    return s


@router.get("/mpesa", response_model=MpesaOut, summary="Get my M-Pesa number")
def get_mpesa(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    prof = db.query(BillingProfile).filter(BillingProfile.user_id == current_user.id).first()
    return {"msisdn": prof.mpesa_msisdn if prof else None}


@router.put(
    "/mpesa",
    response_model=MpesaOut,
    status_code=status.HTTP_200_OK,
    summary="Set/update my M-Pesa number",
)
def set_mpesa(
    payload: MpesaUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    msisdn = _normalize_msisdn(payload.msisdn)
    prof = db.query(BillingProfile).filter(BillingProfile.user_id == current_user.id).first()
    if not prof:
        prof = BillingProfile(user_id=current_user.id, mpesa_msisdn=msisdn)
        db.add(prof)
    else:
        prof.mpesa_msisdn = msisdn
    db.commit()
    return {"msisdn": msisdn}


@router.get(
    "/transactions",
    response_model=list[BillingTransactionOut],
    summary="List my billing transactions",
)
def list_transactions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    txs = (
        db.query(BillingTransaction)
        .filter(BillingTransaction.user_id == current_user.id)
        .order_by(BillingTransaction.created_at.desc())
        .all()
    )
    return txs

