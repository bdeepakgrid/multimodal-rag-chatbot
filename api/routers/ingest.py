import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from api.auth import Role, UserContext, require_roles
from api.deps import get_app_state
from models.schemas import CollectionStats, DeleteDocumentResponse, IngestResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest_documents(
    tenant_id: Annotated[str, Form()] = "default",
    tags: Annotated[str, Form()] = "",
    files: list[UploadFile] = File(...),
    _user: UserContext = Depends(require_roles(Role.TECHNICIAN, Role.REVIEWER, Role.ADMIN)),
) -> IngestResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    state = get_app_state()
    state.qdrant_store.ensure_collection(tenant_id)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    file_data: list[tuple[str, bytes]] = []
    for upload in files:
        content = await upload.read()
        filename = upload.filename or "unknown"
        file_data.append((filename, content))

    total_chunks, source_files, errors = await state.pipeline.ingest_files(
        tenant_id=tenant_id,
        files=file_data,
        tags=tag_list,
    )
    state.retriever.rebuild_bm25(tenant_id)
    state.graph_store.rebuild(tenant_id, state.qdrant_store)

    return IngestResponse(
        chunks_created=total_chunks,
        source_files=source_files,
        errors=errors,
    )


@router.get("/collections/{tenant_id}/stats", response_model=CollectionStats)
async def collection_stats(
    tenant_id: str,
    _user: UserContext = Depends(require_roles(Role.TECHNICIAN, Role.REVIEWER, Role.ADMIN)),
) -> CollectionStats:
    state = get_app_state()
    stats = state.qdrant_store.get_stats(tenant_id)
    return CollectionStats(**stats)


@router.get("/collections/{tenant_id}/document/{source_file:path}/raw")
async def get_raw_document(
    tenant_id: str,
    source_file: str,
    _user: UserContext = Depends(require_roles(Role.TECHNICIAN, Role.REVIEWER, Role.ADMIN)),
):
    state = get_app_state()
    path = state.file_store.get_path(tenant_id, source_file)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Source file not found on disk")
    return FileResponse(path, filename=path.name)


@router.delete(
    "/collections/{tenant_id}/document/{source_file:path}",
    response_model=DeleteDocumentResponse,
)
async def delete_document(
    tenant_id: str,
    source_file: str,
    _user: UserContext = Depends(require_roles(Role.TECHNICIAN, Role.REVIEWER, Role.ADMIN)),
) -> DeleteDocumentResponse:
    state = get_app_state()
    deleted = state.qdrant_store.delete_by_source_file_count(tenant_id, source_file)
    state.file_store.delete(tenant_id, source_file)
    state.retriever.rebuild_bm25(tenant_id)
    state.graph_store.rebuild(tenant_id, state.qdrant_store)
    return DeleteDocumentResponse(deleted_chunks=deleted, source_file=source_file)