import logging

from fastapi import APIRouter, Depends

from api.auth import Role, UserContext, require_roles
from api.deps import get_app_state
from models.schemas import DocumentInfo, DocumentListResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/collections", tags=["collections"])


@router.get("")
async def list_collections(
    _user: UserContext = Depends(require_roles(Role.TECHNICIAN, Role.REVIEWER, Role.ADMIN)),
) -> dict:
    """Lists all available Qdrant collections (tenants)."""
    state = get_app_state()
    try:
        collections = [c.name for c in state.qdrant_store.client.get_collections().collections]
        return {"collections": collections}
    except Exception as e:
        logger.exception("Failed to get collections")
        return {"collections": [], "error": str(e)}


@router.get("/documents", response_model=DocumentListResponse)
async def list_all_documents(
    _user: UserContext = Depends(require_roles(Role.TECHNICIAN, Role.REVIEWER, Role.ADMIN)),
) -> DocumentListResponse:
    """Every ingested document across every knowledge base — the full
    inventory of what the RAG system can actually draw answers from."""
    state = get_app_state()
    documents: list[DocumentInfo] = []
    for tenant_id in state.qdrant_store.list_tenant_ids():
        for doc in state.qdrant_store.list_documents(tenant_id):
            documents.append(DocumentInfo(tenant_id=tenant_id, **doc))

    documents.sort(key=lambda d: (d.tenant_id, d.source_file))
    return DocumentListResponse(
        documents=documents,
        total_documents=len(documents),
        total_chunks=sum(d.chunk_count for d in documents),
    )