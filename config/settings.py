from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ollama_base_url: str = "http://localhost:11434"
    qdrant_url: str = "http://localhost:6333"
    llm_model: str = "qwen2.5vl:7b"
    embed_model: str = "nomic-embed-text"
    chunk_size: int = 512
    chunk_overlap: int = 50
    embedding_batch_size: int = 8
    upsert_batch_size: int = 64
    pdf_ocr_mode: str = "auto"  # auto, always, or never
    feedback_score_weight: float = 0.35
    retrieval_top_k: int = 20
    rerank_top_n: int = 5
    max_context_tokens: int = 4096
    llm_max_tokens: int = 512
    llm_temperature: float = 0.1
    chat_image_max_bytes: int = 8 * 1024 * 1024
    upload_dir: Path = Path("./uploads")
    default_tenant_id: str = "default"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    gradio_port: int = 7860
    embed_dim: int = 768
    confidence_threshold: float = 0.65
    min_rerank_score: float = -2.0  # cross-encoder logit floor; below this a chunk is treated as irrelevant, not just "low confidence"
    agent_max_iterations: int = 4  # cap on how many times the agent may re-search before it must answer
    rrf_k: int = 60
    graph_store_dir: Path = Path("./data/graphs")  # directory to store graph data

    @property
    def upload_path(self) -> Path:
        return self.upload_dir.resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
