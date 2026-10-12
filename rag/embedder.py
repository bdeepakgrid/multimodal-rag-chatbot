import logging

from config.settings import Settings
from models.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class Embedder:
    def __init__(self, ollama: OllamaClient, settings: Settings):
        self.ollama = ollama
        self.settings = settings

    async def embed_text(self, text: str) -> list[float]:
        embedding = await self.ollama.embed_text(text)
        return embedding

    async def embed_batch(self, texts: list[str], batch_size: int = 8) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            for text in batch:
                try:
                    embeddings.append(await self.embed_text(text))
                except Exception as e:
                    logger.error("Embedding failed: %s", e)
                    raise
        return embeddings

    async def embed_query(self, query: str) -> list[float]:
        prefixed = f"search_query: {query}"
        return await self.embed_text(prefixed)
