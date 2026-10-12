import logging
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from config.settings import Settings
from models.schemas import Chunk, SourceType

logger = logging.getLogger(__name__)


class QdrantStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = QdrantClient(url=settings.qdrant_url)
        self.embed_dim = settings.embed_dim

    def collection_name(self, tenant_id: str) -> str:
        safe_id = tenant_id.replace("-", "_").replace(".", "_")
        return f"text_{safe_id}"

    def _list_collections(self) -> list[str]:
        try:
            return [c.name for c in self.client.get_collections().collections]
        except Exception as exc:  # pragma: no cover - depends on external service
            logger.warning("Qdrant not reachable; continuing in degraded mode: %s", exc)
            return []

    def ensure_collection(self, tenant_id: str) -> None:
        name = self.collection_name(tenant_id)
        collections = self._list_collections()
        if not collections:
            return
        if name not in collections:
            try:
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=qmodels.VectorParams(
                        size=self.embed_dim,
                        distance=qmodels.Distance.COSINE,
                    ),
                    hnsw_config=qmodels.HnswConfigDiff(m=16),
                )
                self.client.create_payload_index(
                    collection_name=name,
                    field_name="tenant_id",
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
                self.client.create_payload_index(
                    collection_name=name,
                    field_name="source_file",
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
                logger.info("Created Qdrant collection: %s", name)
            except Exception as exc:  # pragma: no cover - depends on external service
                logger.warning("Qdrant unavailable while creating collection %s: %s", name, exc)

    def _chunk_to_payload(self, chunk: Chunk) -> dict:
        return {
            "tenant_id": chunk.tenant_id,
            "source_file": chunk.source_file,
            "source_type": chunk.source_type.value,
            "page_number": chunk.page_number,
            "timestamp": chunk.timestamp,
            "tags": chunk.tags,
            "raw_file_url": chunk.raw_file_url,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
        }

    def upsert_chunks(self, tenant_id: str, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        self.ensure_collection(tenant_id)
        name = self.collection_name(tenant_id)
        points = []
        for chunk in chunks:
            if chunk.embedding is None:
                raise ValueError(f"Chunk {chunk.id} missing embedding")
            points.append(
                qmodels.PointStruct(
                    id=chunk.id,
                    vector=chunk.embedding,
                    payload=self._chunk_to_payload(chunk),
                )
            )
        try:
            self.client.upsert(collection_name=name, points=points)
        except Exception as exc:  # pragma: no cover - depends on external service
            logger.warning("Qdrant unavailable while upserting chunks for tenant %s: %s", tenant_id, exc)
            return 0
        return len(points)

    def search_dense(
        self,
        tenant_id: str,
        query_vector: list[float],
        top_k: int,
    ) -> list[tuple[str, float, dict]]:
        name = self.collection_name(tenant_id)
        collections = self._list_collections()
        if name not in collections:
            return []

        try:
            response = self.client.query_points(
                collection_name=name,
                query=query_vector,
                limit=top_k,
                query_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="tenant_id",
                            match=qmodels.MatchValue(value=tenant_id),
                        )
                    ]
                ),
            )
        except Exception as exc:  # pragma: no cover - depends on external service
            logger.warning("Qdrant unavailable while dense-searching tenant %s: %s", tenant_id, exc)
            return []
        return [(str(hit.id), hit.score, hit.payload or {}) for hit in response.points]

    def get_all_texts(self, tenant_id: str) -> list[tuple[str, dict]]:
        name = self.collection_name(tenant_id)
        collections = self._list_collections()
        if name not in collections:
            return []

        texts: list[tuple[str, dict]] = []
        offset = None
        try:
            while True:
                records, offset = self.client.scroll(
                    collection_name=name,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for record in records:
                    payload = record.payload or {}
                    texts.append((str(record.id), payload))
                if offset is None:
                    break
        except Exception as exc:  # pragma: no cover - depends on external service
            logger.warning("Qdrant unavailable while loading texts for tenant %s: %s", tenant_id, exc)
            return []
        return texts

    def delete_by_source_file_count(self, tenant_id: str, source_file: str) -> int:
        name = self.collection_name(tenant_id)
        collections = self._list_collections()
        if name not in collections:
            return 0

        to_delete: list[str] = []
        offset = None
        try:
            while True:
                records, offset = self.client.scroll(
                    collection_name=name,
                    scroll_filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="source_file",
                                match=qmodels.MatchValue(value=source_file),
                            ),
                        ]
                    ),
                    limit=100,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
                to_delete.extend(str(r.id) for r in records)
                if offset is None:
                    break

            if to_delete:
                self.client.delete(
                    collection_name=name,
                    points_selector=qmodels.PointIdsList(points=to_delete),
                )
        except Exception as exc:  # pragma: no cover - depends on external service
            logger.warning("Qdrant unavailable while deleting source file %s for tenant %s: %s", source_file, tenant_id, exc)
            return 0
        return len(to_delete)

    def get_stats(self, tenant_id: str) -> dict:
        name = self.collection_name(tenant_id)
        collections = self._list_collections()
        if name not in collections:
            return {"total_chunks": 0, "by_type": {}, "last_updated": None}

        by_type: dict[str, int] = {}
        last_updated: Optional[str] = None
        total = 0
        offset = None
        try:
            while True:
                records, offset = self.client.scroll(
                    collection_name=name,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for record in records:
                    total += 1
                    payload = record.payload or {}
                    st = payload.get("source_type", "unknown")
                    by_type[st] = by_type.get(st, 0) + 1
                    ts = payload.get("timestamp")
                    if ts and (last_updated is None or ts > last_updated):
                        last_updated = ts
                if offset is None:
                    break
        except Exception as exc:  # pragma: no cover - depends on external service
            logger.warning("Qdrant unavailable while fetching stats for tenant %s: %s", tenant_id, exc)
            return {"total_chunks": 0, "by_type": {}, "last_updated": None}
        return {"total_chunks": total, "by_type": by_type, "last_updated": last_updated}

    def list_documents(self, tenant_id: str) -> list[dict]:
        """One row per distinct source file in this knowledge base, with
        chunk count, type, tags, and most recent ingestion timestamp."""
        name = self.collection_name(tenant_id)
        collections = self._list_collections()
        if name not in collections:
            return []

        docs: dict[str, dict] = {}
        offset = None
        try:
            while True:
                records, offset = self.client.scroll(
                    collection_name=name,
                    limit=200,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for record in records:
                    payload = record.payload or {}
                    source_file = payload.get("source_file", "unknown")
                    entry = docs.setdefault(
                        source_file,
                        {
                            "source_file": source_file,
                            "source_type": payload.get("source_type", "unknown"),
                            "chunk_count": 0,
                            "tags": set(),
                            "last_updated": None,
                        },
                    )
                    entry["chunk_count"] += 1
                    entry["tags"].update(payload.get("tags", []) or [])
                    ts = payload.get("timestamp")
                    if ts and (entry["last_updated"] is None or ts > entry["last_updated"]):
                        entry["last_updated"] = ts
                if offset is None:
                    break
        except Exception as exc:  # pragma: no cover - depends on external service
            logger.warning("Qdrant unavailable while listing documents for tenant %s: %s", tenant_id, exc)
            return []

        results = []
        for entry in docs.values():
            entry["tags"] = sorted(entry["tags"])
            results.append(entry)
        results.sort(key=lambda d: d["source_file"])
        return results

    def payload_to_chunk(self, chunk_id: str, payload: dict) -> Chunk:
        return Chunk(
            id=chunk_id,
            text=payload.get("text", ""),
            tenant_id=payload.get("tenant_id", ""),
            source_file=payload.get("source_file", ""),
            source_type=SourceType(payload.get("source_type", "text")),
            page_number=payload.get("page_number"),
            timestamp=payload.get("timestamp", ""),
            tags=payload.get("tags", []),
            raw_file_url=payload.get("raw_file_url", ""),
            chunk_index=payload.get("chunk_index", 0),
        )

    def list_tenant_ids(self) -> list[str]:
        """Every knowledge base (tenant) that currently has a collection in Qdrant."""
        collections = self._list_collections()
        tenant_ids = []
        for name in collections:
            if name.startswith("text_"):
                tenant_ids.append(name[len("text_"):])
        return tenant_ids