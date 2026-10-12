from storage.feedback_store import FeedbackStore
from config.settings import Settings
from models.schemas import Chunk, RetrievedChunk, SourceType
from rag.retriever import HybridRetriever


def test_feedback_store_persists_pending_state_and_scores(tmp_path):
    db_path = tmp_path / "feedback.sqlite3"
    store = FeedbackStore(db_path)
    store.save_pending(
        session_id="session-1",
        tenant_id="default",
        query_text="robot heat error",
        chunk_id="chunk-a",
        incident_id="MX-017",
        source_file="manual.pdf",
    )

    # A new store instance models an application restart.
    restarted = FeedbackStore(db_path)
    pending = restarted.get_pending("session-1")
    assert pending["chunk_id"] == "chunk-a"
    assert pending["incident_id"] == "MX-017"

    restarted.record_event(
        tenant_id="default",
        session_id="session-1",
        query_text="robot heat error",
        outcome="confirmed",
        chunk_id="chunk-a",
        incident_id="MX-017",
        source_file="manual.pdf",
    )
    restarted.record_event(
        tenant_id="default",
        session_id="session-2",
        query_text="robot heat error",
        outcome="rejected",
        chunk_id="chunk-b",
        incident_id="MX-018",
        source_file="manual.pdf",
    )

    scores = restarted.get_chunk_scores({"default"})
    assert scores[("default", "chunk-a")] == 1.0
    assert scores[("default", "chunk-b")] == -1.0

    restarted.delete_pending("session-1")
    assert restarted.get_pending("session-1") is None


def test_feedback_signal_changes_retrieval_order(tmp_path, monkeypatch):
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    store.record_event("default", "s", "robot heat", "confirmed", "chunk-a", "MX-017", "manual.pdf")
    store.record_event("default", "s", "robot heat", "rejected", "chunk-b", "MX-018", "manual.pdf")

    class FakeReranker:
        def predict(self, pairs):
            return [0.10, 0.20]

    monkeypatch.setattr("rag.retriever.get_cross_encoder", lambda: FakeReranker())
    retriever = HybridRetriever(Settings(), object(), object(), store)
    candidates = [
        RetrievedChunk(
            chunk=Chunk.new("Incident MX-017", "default", "manual.pdf", SourceType.PDF, 17, [], "", 0),
        ),
        RetrievedChunk(
            chunk=Chunk.new("Incident MX-018", "default", "manual.pdf", SourceType.PDF, 18, [], "", 1),
        ),
    ]
    candidates[0].chunk.id = "chunk-a"
    candidates[1].chunk.id = "chunk-b"

    ranked = retriever._rerank("robot heat", candidates, 2)

    assert ranked[0].chunk.id == "chunk-a"
