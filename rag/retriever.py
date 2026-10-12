import logging
import re
from typing import Any, Optional

from rank_bm25 import BM25Okapi

from config.settings import Settings
from models.schemas import Chunk, RetrievedChunk
from rag.embedder import Embedder
from storage.qdrant_store import QdrantStore
from storage.feedback_store import FeedbackStore

logger = logging.getLogger(__name__)

_cross_encoder: Optional[Any] = None
_reranker_unavailable = False


def get_cross_encoder() -> Any | None:
    global _cross_encoder, _reranker_unavailable
    if _cross_encoder is None:
        if _reranker_unavailable:
            return None
        try:
            from sentence_transformers import CrossEncoder

            logger.info("Loading cross-encoder reranker...")
            _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        except Exception as exc:
            _reranker_unavailable = True
            logger.warning("Cross-encoder unavailable; using hybrid retrieval scores: %s", exc)
    return _cross_encoder


def warm_reranker() -> None:
    get_cross_encoder()


class BM25Index:
    def __init__(self):
        self.chunk_ids: list[str] = []
        self.payloads: dict[str, dict] = {}
        self._bm25: Optional[BM25Okapi] = None
        self._tokenized: list[list[str]] = []

    def rebuild(self, entries: list[tuple[str, dict]]) -> None:
        self.chunk_ids = []
        self.payloads = {}
        self._tokenized = []
        for chunk_id, payload in entries:
            text = payload.get("text", "")
            if not text.strip():
                continue
            self.chunk_ids.append(chunk_id)
            self.payloads[chunk_id] = payload
            self._tokenized.append(_tokenize(text))
        self._bm25 = BM25Okapi(self._tokenized) if self._tokenized else None

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        if not self._bm25 or not self.chunk_ids:
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(zip(self.chunk_ids, scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def reciprocal_rank_fusion(
    ranked_lists: list[list[tuple[str, float]]],
    k: int = 60,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, (doc_id, _) in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


class HybridRetriever:
    def __init__(
        self,
        settings: Settings,
        qdrant_store: QdrantStore,
        embedder: Embedder,
        feedback_store: FeedbackStore | None = None,
    ):
        self.settings = settings
        self.qdrant_store = qdrant_store
        self.embedder = embedder
        self.feedback_store = feedback_store
        self._bm25_indexes: dict[str, BM25Index] = {}

    def rebuild_bm25(self, tenant_id: str) -> None:
        entries = self.qdrant_store.get_all_texts(tenant_id)
        index = BM25Index()
        index.rebuild(entries)
        self._bm25_indexes[tenant_id] = index
        logger.info("Rebuilt BM25 index for tenant %s: %d docs", tenant_id, len(entries))

    def ensure_bm25(self, tenant_id: str) -> BM25Index:
        if tenant_id not in self._bm25_indexes:
            self.rebuild_bm25(tenant_id)
        return self._bm25_indexes[tenant_id]

    async def retrieve(self, query: str, tenant_id: str) -> list[RetrievedChunk]:
        top_k = self.settings.retrieval_top_k
        rerank_n = self.settings.rerank_top_n

        candidates = await self._gather_candidates(query, tenant_id, top_k)
        return self._rerank(query, candidates, rerank_n)

    async def retrieve_across_all(self, query: str) -> list[RetrievedChunk]:
        """Search every knowledge base and return the globally best-matching
        chunks, reranked together — the caller never has to know or pick
        which collection the answer came from."""
        top_k = self.settings.retrieval_top_k
        rerank_n = self.settings.rerank_top_n

        tenant_ids = self.qdrant_store.list_tenant_ids()
        if not tenant_ids:
            return []

        all_candidates: list[RetrievedChunk] = []
        for tenant_id in tenant_ids:
            all_candidates.extend(await self._gather_candidates(query, tenant_id, top_k))

        # Dense/BM25 scores aren't comparable across separately-fused
        # per-collection lists, so global ranking happens only after the
        # cross-encoder scores everything on the same scale.
        return self._rerank(query, all_candidates, rerank_n)

    async def _gather_candidates(
        self, query: str, tenant_id: str, top_k: int
    ) -> list[RetrievedChunk]:
        query_vector = await self.embedder.embed_query(query)
        dense_results = self.qdrant_store.search_dense(tenant_id, query_vector, top_k)
        dense_ranked = [(cid, score) for cid, score, _ in dense_results]

        bm25_index = self.ensure_bm25(tenant_id)
        bm25_ranked = bm25_index.search(query, top_k)

        fused = reciprocal_rank_fusion([dense_ranked, bm25_ranked], k=self.settings.rrf_k)

        candidate_ids = [doc_id for doc_id, _ in fused[: top_k * 2]]
        id_to_dense = {cid: score for cid, score, _ in dense_results}
        id_to_bm25 = dict(bm25_ranked)
        id_to_rrf = dict(fused)

        payload_map: dict[str, dict] = {}
        for cid, _, payload in dense_results:
            payload_map[cid] = payload
        for cid in bm25_index.chunk_ids:
            if cid not in payload_map:
                payload_map[cid] = bm25_index.payloads[cid]

        candidates: list[RetrievedChunk] = []
        for cid in candidate_ids:
            payload = payload_map.get(cid) or bm25_index.payloads.get(cid)
            if not payload:
                continue
            chunk = self.qdrant_store.payload_to_chunk(cid, payload)
            candidates.append(
                RetrievedChunk(
                    chunk=chunk,
                    dense_score=id_to_dense.get(cid, 0.0),
                    bm25_score=id_to_bm25.get(cid, 0.0),
                    rrf_score=id_to_rrf.get(cid, 0.0),
                )
            )
        return candidates

    def _rerank(
        self, query: str, candidates: list[RetrievedChunk], rerank_n: int
    ) -> list[RetrievedChunk]:
        if not candidates:
            return []

        cross_encoder = get_cross_encoder()
        if cross_encoder is None:
            for candidate in candidates:
                candidate.rerank_score = candidate.rrf_score
        else:
            pairs = [[query, c.chunk.text] for c in candidates]
            rerank_scores = cross_encoder.predict(pairs)
            for candidate, score in zip(candidates, rerank_scores):
                candidate.rerank_score = float(score)

        if self.feedback_store is not None:
            tenant_ids = {candidate.chunk.tenant_id for candidate in candidates}
            feedback_scores = self.feedback_store.get_chunk_scores(tenant_ids)
            for candidate in candidates:
                signal = feedback_scores.get((candidate.chunk.tenant_id, candidate.chunk.id), 0.0)
                candidate.rerank_score += self.settings.feedback_score_weight * signal

        candidates.sort(key=lambda c: c.rerank_score, reverse=True)

        # A cross-encoder score is on the same scale for every candidate
        # regardless of which knowledge base it came from, so this is the
        # right place to enforce an absolute "is this actually relevant at
        # all" floor — not just take the top N no matter how bad they are.
        # Without this, an off-topic query still returns *something*, which
        # then gets forced into the prompt as if it were real context.
        relevant = [c for c in candidates if c.rerank_score >= self.settings.min_rerank_score]
        return relevant[:rerank_n]
