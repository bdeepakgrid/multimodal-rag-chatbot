"""
storage/graph_store.py

Local-filesystem persistence for per-tenant DiagnosticGraph objects.
Mirrors storage/local_file_store.py's POC-scope approach: no extra
service, JSON on disk, one file per tenant.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from rag.diagnostic_graph import DiagnosticGraph, build_from_rows
from storage.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


class GraphStore:
    def __init__(self, base_dir: str = "./data/graphs"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, DiagnosticGraph] = {}

    def _path(self, tenant_id: str) -> Path:
        safe_id = tenant_id.replace("/", "_")
        return self.base_dir / f"{safe_id}.json"

    def save(self, dg: DiagnosticGraph) -> None:
        path = self._path(dg.tenant_id)
        path.write_text(json.dumps(dg.to_dict()), encoding="utf-8")
        self._cache[dg.tenant_id] = dg
        logger.info("Saved diagnostic graph for %s -> %s", dg.tenant_id, path)

    def load(self, tenant_id: str) -> DiagnosticGraph | None:
        if tenant_id in self._cache:
            return self._cache[tenant_id]
        path = self._path(tenant_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        dg = DiagnosticGraph.from_dict(tenant_id, data)
        self._cache[tenant_id] = dg
        return dg

    def rebuild(self, tenant_id: str, qdrant_store: QdrantStore) -> DiagnosticGraph:
        """Same trigger point as HybridRetriever.rebuild_bm25 — call this
        right after ingestion upserts chunks for a tenant."""
        rows = qdrant_store.get_all_texts(tenant_id)
        dg = build_from_rows(tenant_id, rows)
        self.save(dg)
        return dg

    def ensure(self, tenant_id: str, qdrant_store: QdrantStore) -> DiagnosticGraph:
        existing = self.load(tenant_id)
        if existing is not None:
            return existing
        return self.rebuild(tenant_id, qdrant_store)
