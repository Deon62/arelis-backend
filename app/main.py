import json
import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .database import Base, engine
from .routers import auth
from .auth import get_current_user
from .models import User

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="The Foundry Africa API",
    description="Backend API for The Foundry Africa — Arelis AI legal platform for Kenyan startups and businesses.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)


@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "The Foundry Africa API"}


# ── AI Chat ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Arelis, the AI legal assistant built by The Foundry Africa. You specialise exclusively in Kenyan law for startups and businesses.

Your knowledge covers:
- The Constitution of Kenya (2010)
- The Companies Act (No. 17 of 2015)
- The Data Protection Act (No. 24 of 2019)
- The Employment Act (Cap. 226)
- The Labour Relations Act (2007)
- The Consumer Protection Act (2012)
- Contract law principles under Kenyan jurisdiction
- Business registration and compliance (BRS, KRA, NHIF, NSSF)
- Intellectual property law (KIPI, trademarks, patents, copyright)
- Tax law (Income Tax Act, VAT Act)
- Regulatory frameworks (CBK, CMA, CAK, KEBS)

Rules you MUST follow:
1. Only answer questions related to Kenyan law, legal compliance, and business legal matters.
2. If a question is outside Kenyan law or not related to business/startup legal matters, politely decline and explain your scope.
3. You can draft legal documents when asked: terms of service, privacy policies, NDAs, employment contracts, shareholder agreements, etc. Always tailor them to Kenyan law.
4. Always cite the relevant Kenyan law, act, or section when possible.
5. Include disclaimers that you are an AI assistant and your responses do not constitute formal legal advice. Recommend consulting a licensed Kenyan advocate for critical matters.
6. Be concise, professional, and helpful. Use plain language that founders and business owners can understand.
7. When unsure, say so honestly rather than guessing.
8. Never provide advice on criminal law, family law, personal injury, or other non-business matters."""


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@app.get("/api/chat/ping", tags=["AI Chat"])
def chat_ping():
    return {"status": "ok", "endpoint": "chat"}


@app.post("/api/chat/stream", tags=["AI Chat"])
async def chat_stream(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY not configured")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in payload.messages:
        messages.append({"role": m.role, "content": m.content})

    async def generate():
        stream = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.3,
            max_tokens=2048,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield f"data: {json.dumps({'token': delta.content})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
