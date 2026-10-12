import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import APIKeyAuthMiddleware
from api.auth_db import init_auth_db
from api.deps import init_app_state, shutdown_app_state
from api.routers import chat, ingest, collections, auth
from rag.retriever import warm_reranker

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_auth_db()
    state = init_app_state()
    warm_reranker()
    try:
        state.qdrant_store.ensure_collection(state.settings.default_tenant_id)
    except Exception as exc:
        logger.warning("Qdrant not available during startup; continuing in degraded mode: %s", exc)

    healthy = await state.ollama.health_check()
    llm_ok, llm_msg = await state.ollama.llm_health_check()
    if healthy and llm_ok:
        logger.info("Ollama health check passed (LLM: %s)", llm_msg)
    elif healthy:
        logger.warning("Ollama reachable but LLM misconfigured: %s", llm_msg)
    else:
        logger.warning(
            "Ollama not reachable at %s — ensure 'ollama serve' is running",
            state.settings.ollama_base_url,
        )

    yield
    await shutdown_app_state()


app = FastAPI(
    title="Multimodal RAG Chatbot",
    description="Phase 1 — Core RAG API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(APIKeyAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(ingest.router, prefix="/api/v1")
app.include_router(collections.router, prefix="/api/v1")


@app.get("/health")
async def health():
    from api.deps import get_app_state

    state = get_app_state()
    ollama_ok = await state.ollama.health_check()
    llm_ok, llm_msg = await state.ollama.llm_health_check()
    return {
        "status": "ok" if ollama_ok and llm_ok else "degraded",
        "ollama": ollama_ok,
        "llm_model": state.settings.llm_model,
        "llm_ready": llm_ok,
        "llm_message": llm_msg,
    }


