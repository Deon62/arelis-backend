import json
import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .routers import auth
from .routers import kb
from .routers import sessions
from .auth import get_current_user
from .models import KnowledgeBaseDocument, User

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
app.include_router(kb.router)
app.include_router(sessions.router)


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

RAG_GUIDANCE = """
Definitions:
- "Knowledge Base" ALWAYS means the user's own uploaded PDFs in this app (not an external dataset, not generic internet knowledge).

You have access to the user's uploaded Knowledge Base documents (PDFs) via retrieval. If the user asks whether you can access their Knowledge Base, the correct answer is YES: you can search and use their uploaded PDFs when it helps answer their question.

You may be provided with optional excerpts from the user's uploaded Knowledge Base documents (PDFs).

How to use them:
- Use the excerpts ONLY when they are relevant to the user's question.
- If the excerpts are not relevant, ignore them and answer normally.
- If you use the excerpts, still provide broader Kenyan-law context and practical recommendations beyond the document text.
- Even when using excerpts, improve the answer: add missing considerations, challenge assumptions, and recommend next steps.
- When you rely on the excerpts for a claim, include a short "Sources" section at the end with bullet points like:
  - <filename> (p.<page>)
"""


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
    request: Request,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY not configured")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    history = [{"role": m.role, "content": m.content} for m in payload.messages]
    query = ""
    for m in reversed(payload.messages):
        if m.role == "user":
            query = m.content
            break

    kb_context_message = None
    kb_inventory_message = None
    try:
        docs = (
            db.query(KnowledgeBaseDocument)
            .filter(KnowledgeBaseDocument.user_id == current_user.id)
            .order_by(KnowledgeBaseDocument.created_at.desc())
            .limit(8)
            .all()
        )
        if docs:
            names = ", ".join([d.filename for d in docs])
            kb_inventory_message = {
                "role": "system",
                "content": f"User Knowledge Base contains {len(docs)} PDF(s) (most recent first): {names}.",
            }
    except Exception:
        kb_inventory_message = None

    try:
        from .rag_store import retrieve_chunks, should_use_context

        chunks = retrieve_chunks(user_id=current_user.id, query=query, k=6) if query else []
        if query and should_use_context(query, chunks):
            top = chunks[:4]
            context_lines = []
            for i, c in enumerate(top, start=1):
                src = f"{c.filename}"
                if c.page:
                    src += f" (p.{c.page})"
                context_lines.append(f"[{i}] {src}\n{c.text}")
            kb_context_message = {
                "role": "system",
                "content": "Knowledge Base excerpts (user-provided):\n<kb>\n"
                + "\n\n".join(context_lines)
                + "\n</kb>",
            }
    except Exception:
        kb_context_message = None

    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + RAG_GUIDANCE}]
    if kb_inventory_message:
        messages.append(kb_inventory_message)
    if kb_context_message:
        messages.append(kb_context_message)
    messages.extend(history)

    async def generate():
        try:
            stream = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.3,
                max_tokens=2048,
                stream=True,
            )
            for chunk in stream:
                if await request.is_disconnected():
                    break
                delta = chunk.choices[0].delta
                if delta.content:
                    yield f"data: {json.dumps({'token': delta.content})}\n\n"
        except Exception:
            # Client disconnects or upstream issues should not crash the server.
            return
        finally:
            if not await request.is_disconnected():
                yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
