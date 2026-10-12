from dataclasses import dataclass
from typing import Optional

from config.settings import Settings, get_settings
from ingestion.pipeline import IngestionPipeline
from models.ollama_client import OllamaClient
from rag.agent import RetrievalAgent
from rag.context_builder import ContextBuilder
from rag.embedder import Embedder
from rag.retriever import HybridRetriever, warm_reranker
from storage.graph_store import GraphStore
from storage.feedback_store import FeedbackStore
from storage.local_file_store import LocalFileStore
from storage.qdrant_store import QdrantStore


@dataclass
class AppState:
    settings: Settings
    ollama: OllamaClient
    qdrant_store: QdrantStore
    file_store: LocalFileStore
    embedder: Embedder
    retriever: HybridRetriever
    context_builder: ContextBuilder
    agent: RetrievalAgent
    pipeline: IngestionPipeline
    graph_store: GraphStore
    feedback_store: FeedbackStore


_state: Optional[AppState] = None


def get_app_state() -> AppState:
    if _state is None:
        raise RuntimeError("Application not initialized")
    return _state


def init_app_state() -> AppState:
    global _state
    settings = get_settings()
    ollama = OllamaClient(settings)
    qdrant_store = QdrantStore(settings)
    file_store = LocalFileStore(settings)
    embedder = Embedder(ollama, settings)
    feedback_store = FeedbackStore()
    retriever = HybridRetriever(settings, qdrant_store, embedder, feedback_store)
    context_builder = ContextBuilder(settings)
    graph_store = GraphStore(base_dir=settings.graph_store_dir)
    agent = RetrievalAgent(retriever, ollama, settings, graph_store)
    pipeline = IngestionPipeline(settings, file_store, qdrant_store, embedder)
    _state = AppState(
        settings=settings,
        ollama=ollama,
        qdrant_store=qdrant_store,
        file_store=file_store,
        embedder=embedder,
        retriever=retriever,
        context_builder=context_builder,
        agent=agent,
        pipeline=pipeline,
        graph_store=graph_store,
        feedback_store=feedback_store,
    )
    return _state


async def shutdown_app_state() -> None:
    global _state
    if _state:
        await _state.ollama.close()
        _state = None
