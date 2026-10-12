from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    EXCEL = "excel"
    PDF = "pdf"
    TEXT = "text"
    DOCX = "docx"
    CSV = "csv"


@dataclass
class TextBlock:
    text: str
    page_number: Optional[int]
    source_type: SourceType


@dataclass
class ParsedDocument:
    source_file: str
    source_type: SourceType
    blocks: list[TextBlock] = field(default_factory=list)


@dataclass
class Chunk:
    id: str
    text: str
    tenant_id: str
    source_file: str
    source_type: SourceType
    page_number: Optional[int]
    timestamp: str
    tags: list[str]
    raw_file_url: str
    chunk_index: int
    embedding: Optional[list[float]] = None

    @classmethod
    def new(
        cls,
        text: str,
        tenant_id: str,
        source_file: str,
        source_type: SourceType,
        page_number: Optional[int],
        tags: list[str],
        raw_file_url: str,
        chunk_index: int,
        embedding: Optional[list[float]] = None,
    ) -> "Chunk":
        return cls(
            id=str(uuid4()),
            text=text,
            tenant_id=tenant_id,
            source_file=source_file,
            source_type=source_type,
            page_number=page_number,
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            tags=tags,
            raw_file_url=raw_file_url,
            chunk_index=chunk_index,
            embedding=embedding,
        )


@dataclass
class RetrievedChunk:
    chunk: Chunk
    dense_score: float = 0.0
    bm25_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float = 0.0


class SourceCitation(BaseModel):
    tenant_id: str
    file: str
    page: Optional[int] = None
    snippet: str
    chunk_index: int


class ClarificationOption(BaseModel):
    id: str
    label: str
    context: str
    search_hint: str


class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None


class AgentStep(BaseModel):
    thought: str
    query: str
    results_found: int
    best_score: Optional[float] = None


class GraphMatch(BaseModel):
    nodes: list[dict]         # [{"role": "symptom", "label": "..."}, ...]
    confidence_weight: int     # min edge occurrence count along the path
    chunk_ids: list[str]

class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceCitation]
    confidence: float
    agent_steps: list[AgentStep] = []
    graph_matches: list[GraphMatch] = []
    suggestions: list[ClarificationOption] = []


class IngestResponse(BaseModel):
    chunks_created: int
    source_files: list[str]
    errors: list[str] = Field(default_factory=list)


class CollectionStats(BaseModel):
    total_chunks: int
    by_type: dict[str, int]
    last_updated: Optional[str] = None


class DeleteDocumentResponse(BaseModel):
    deleted_chunks: int
    source_file: str


class DocumentInfo(BaseModel):
    tenant_id: str
    source_file: str
    source_type: str
    chunk_count: int
    tags: list[str]
    last_updated: Optional[str] = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]
    total_documents: int
    total_chunks: int
