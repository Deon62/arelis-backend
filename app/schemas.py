from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    first_name: str
    last_name: str
    email: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: str | None = None


class KBDocumentOut(BaseModel):
    id: str
    filename: str
    content_type: str | None = None
    size_bytes: int
    created_at: datetime

    model_config = {"from_attributes": True}


class LawyerSessionCreate(BaseModel):
    topic: str
    date: str  # YYYY-MM-DD
    time: str  # e.g. "09:00 AM"
    notes: str | None = None


class LawyerSessionOut(BaseModel):
    id: str
    topic: str
    scheduled_at: datetime
    status: str
    notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MpesaUpdate(BaseModel):
    msisdn: str


class MpesaOut(BaseModel):
    msisdn: str | None = None


class BillingTransactionOut(BaseModel):
    id: str
    description: str
    amount_kes: int
    created_at: datetime

    model_config = {"from_attributes": True}
