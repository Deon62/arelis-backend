import os
import re
from dataclasses import dataclass
from typing import Iterable

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9]+", (text or "").lower())


class LightHashEmbeddings(Embeddings):
    """
    Lightweight deterministic embeddings.

    This avoids heavy ML deps for now. You can swap to real embeddings later.
    """

    def __init__(self, dim: int = 384):
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for t in _tokenize(text):
            i = hash(t) % self.dim
            vec[i] += 1.0
        # L2 normalize
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


@dataclass
class RagChunk:
    text: str
    doc_id: str
    filename: str
    page: int | None = None
    score: float | None = None


_VECTORSTORE: Chroma | None = None


def get_vectorstore() -> Chroma:
    global _VECTORSTORE
    if _VECTORSTORE is not None:
        return _VECTORSTORE

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    persist_dir = os.getenv("CHROMA_DIR", os.path.join(base_dir, "chroma_data"))
    os.makedirs(persist_dir, exist_ok=True)

    _VECTORSTORE = Chroma(
        collection_name="kb_chunks",
        persist_directory=persist_dir,
        embedding_function=LightHashEmbeddings(),
    )
    return _VECTORSTORE


def chunk_text(text: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=900,
        chunk_overlap=160,
        separators=["\n\n", "\n", " ", ""],
    )
    return splitter.split_text(text or "")


def index_pages(
    *,
    user_id: str,
    doc_id: str,
    filename: str,
    pages: Iterable[tuple[int, str]],
) -> int:
    """
    pages: iterable of (page_number_1_indexed, page_text)
    """
    vectorstore = get_vectorstore()
    docs: list[Document] = []
    ids: list[str] = []

    for page_num, page_text in pages:
        for ci, chunk in enumerate(chunk_text(page_text)):
            chunk = chunk.strip()
            if not chunk:
                continue
            ids.append(f"{user_id}:{doc_id}:{page_num}:{ci}")
            docs.append(
                Document(
                    page_content=chunk,
                    metadata={
                        "user_id": user_id,
                        "doc_id": doc_id,
                        "filename": filename,
                        "page": page_num,
                    },
                )
            )

    if docs:
        vectorstore.add_documents(docs, ids=ids)
        try:
            vectorstore.persist()
        except Exception:
            # Persist isn't always required depending on Chroma version; ignore safely.
            pass

    return len(docs)


def delete_doc_index(*, user_id: str, doc_id: str) -> None:
    vectorstore = get_vectorstore()
    # Chroma supports metadata where clause
    vectorstore._collection.delete(where={"user_id": user_id, "doc_id": doc_id})
    try:
        vectorstore.persist()
    except Exception:
        pass


_STOP = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "are",
    "was",
    "were",
    "you",
    "your",
    "into",
    "about",
    "can",
    "will",
    "what",
    "how",
    "why",
    "when",
    "where",
    "which",
    "their",
    "they",
    "them",
    "not",
    "but",
    "also",
}


def _keywords(query: str) -> list[str]:
    kws = []
    for t in _tokenize(query):
        if len(t) < 4:
            continue
        if t in _STOP:
            continue
        kws.append(t)
    return kws[:12]


def retrieve_chunks(*, user_id: str, query: str, k: int = 6) -> list[RagChunk]:
    vectorstore = get_vectorstore()
    results = vectorstore.similarity_search_with_score(query, k=k, filter={"user_id": user_id})
    chunks: list[RagChunk] = []
    for doc, score in results:
        chunks.append(
            RagChunk(
                text=doc.page_content,
                doc_id=str(doc.metadata.get("doc_id", "")),
                filename=str(doc.metadata.get("filename", "")),
                page=int(doc.metadata.get("page")) if doc.metadata.get("page") is not None else None,
                score=float(score) if score is not None else None,
            )
        )
    return chunks


def should_use_context(query: str, chunks: list[RagChunk]) -> bool:
    if not chunks:
        return False
    kws = _keywords(query)
    if not kws:
        return False
    best = 0
    for c in chunks[:4]:
        t = (c.text or "").lower()
        overlap = sum(1 for kw in kws if kw in t)
        best = max(best, overlap)
    return best >= 2

