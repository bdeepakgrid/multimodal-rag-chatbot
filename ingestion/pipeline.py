import logging
from dataclasses import dataclass, field
from pathlib import Path

from config.settings import Settings
from ingestion.chunker import Chunker
from ingestion.parsers.docling_parser import DoclingParser, SUPPORTED_EXTENSIONS
from models.schemas import Chunk
from rag.embedder import Embedder
from storage.local_file_store import LocalFileStore
from storage.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    chunks_created: int = 0
    source_file: str = ""
    errors: list[str] = field(default_factory=list)


class IngestionPipeline:
    def __init__(
        self,
        settings: Settings,
        file_store: LocalFileStore,
        qdrant_store: QdrantStore,
        embedder: Embedder,
    ):
        self.settings = settings
        self.file_store = file_store
        self.qdrant_store = qdrant_store
        self.embedder = embedder
        self.parser = DoclingParser(settings.pdf_ocr_mode)
        self.chunker = Chunker(settings)

    async def ingest_file(
        self,
        tenant_id: str,
        file_path: Path,
        tags: list[str] | None = None,
        content: bytes | None = None,
        filename: str | None = None,
    ) -> IngestResult:
        tags = tags or []
        name = filename or file_path.name
        result = IngestResult(source_file=name)

        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            result.errors.append(f"Unsupported file type: {suffix}")
            return result

        try:
            if content is not None:
                raw_url = self.file_store.save(tenant_id, name, content)
                tmp_path = self.file_store.get_path(tenant_id, name)
            else:
                content = file_path.read_bytes()
                raw_url = self.file_store.save(tenant_id, name, content)
                tmp_path = file_path

            parsed = self.parser.parse(tmp_path, name)
            chunks = self.chunker.split_document(parsed, tenant_id, tags, raw_url)

            if not chunks:
                result.errors.append("No content extracted from file")
                return result

            # Bound both embedding and Qdrant memory use. Large manuals can
            # contain thousands of chunks, so do not hold all vectors at once.
            for start in range(0, len(chunks), self.settings.upsert_batch_size):
                batch = chunks[start : start + self.settings.upsert_batch_size]
                embeddings = await self.embedder.embed_batch(
                    [chunk.text for chunk in batch],
                    batch_size=self.settings.embedding_batch_size,
                )
                for chunk, emb in zip(batch, embeddings):
                    chunk.embedding = emb
                result.chunks_created += self.qdrant_store.upsert_chunks(tenant_id, batch)

            logger.info("Ingested %s: %d chunks for tenant %s", name, result.chunks_created, tenant_id)
        except Exception as e:
            logger.exception("Ingestion failed for %s", name)
            result.errors.append(str(e))

        return result

    async def ingest_files(
        self,
        tenant_id: str,
        files: list[tuple[str, bytes]],
        tags: list[str] | None = None,
    ) -> tuple[int, list[str], list[str]]:
        total_chunks = 0
        source_files: list[str] = []
        errors: list[str] = []

        for filename, content in files:
            result = await self.ingest_file(
                tenant_id=tenant_id,
                file_path=Path(filename),
                tags=tags,
                content=content,
                filename=filename,
            )
            if result.chunks_created:
                total_chunks += result.chunks_created
                source_files.append(result.source_file)
            errors.extend(result.errors)

        return total_chunks, source_files, errors
