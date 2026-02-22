import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import KnowledgeBaseDocument, User
from ..rag_store import delete_doc_index, index_pages
from ..schemas import KBDocumentOut

router = APIRouter(prefix="/api/kb", tags=["Knowledge Base"])


def _storage_root() -> Path:
    base = Path(__file__).resolve().parents[2]  # backend/app
    root = Path(os.getenv("KB_STORAGE_DIR", str(base / "storage")))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_name(name: str) -> str:
    name = (name or "document").strip().replace("\\", "_").replace("/", "_")
    return name[:120]


def _extract_pdf_pages(path: Path) -> list[tuple[int, str]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append((i + 1, text))
    return pages


@router.get("/documents", response_model=list[KBDocumentOut], summary="List uploaded documents")
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    docs = (
        db.query(KnowledgeBaseDocument)
        .filter(KnowledgeBaseDocument.user_id == current_user.id)
        .order_by(KnowledgeBaseDocument.created_at.desc())
        .all()
    )
    return docs


@router.post(
    "/upload",
    response_model=list[KBDocumentOut],
    status_code=status.HTTP_201_CREATED,
    summary="Upload documents (PDF) to Knowledge Base",
)
async def upload_documents(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    root = _storage_root() / current_user.id
    root.mkdir(parents=True, exist_ok=True)

    created: list[KnowledgeBaseDocument] = []

    for f in files:
        filename = _safe_name(f.filename)
        content_type = f.content_type or ""

        # Start with PDFs (extend later)
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF uploads are supported for now")

        doc_id = str(uuid.uuid4())
        dst = root / f"{doc_id}_{filename}"
        data = await f.read()
        dst.write_bytes(data)

        doc = KnowledgeBaseDocument(
            id=doc_id,
            user_id=current_user.id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(data),
            storage_path=str(dst),
        )
        db.add(doc)
        created.append(doc)

        pages = _extract_pdf_pages(dst)
        index_pages(
            user_id=current_user.id,
            doc_id=doc_id,
            filename=filename,
            pages=pages,
        )

    db.commit()
    for d in created:
        db.refresh(d)

    return created


@router.delete(
    "/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document from Knowledge Base",
)
def delete_document(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = (
        db.query(KnowledgeBaseDocument)
        .filter(KnowledgeBaseDocument.id == doc_id, KnowledgeBaseDocument.user_id == current_user.id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete from vector store first
    delete_doc_index(user_id=current_user.id, doc_id=doc_id)

    # Delete stored file
    try:
        Path(doc.storage_path).unlink(missing_ok=True)
    except Exception:
        pass

    db.delete(doc)
    db.commit()
    return None

