"""Offline smoke tests — no Ollama/Qdrant required."""

from pathlib import Path

from config.settings import get_settings
from ingestion.chunker import Chunker
from ingestion.parsers.docling_parser import DoclingParser
from rag.context_builder import ContextBuilder
from rag.retriever import reciprocal_rank_fusion
from models.schemas import Chunk, ParsedDocument, RetrievedChunk, SourceType, TextBlock
from api.routers.chat import _clarification_options_for, _classify_query, _is_greeting, _needs_clarification


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_txt():
    parser = DoclingParser()
    doc = parser.parse(FIXTURES / "maintenance_log.txt", "maintenance_log.txt")
    assert len(doc.blocks) == 1
    assert "E-2047" in doc.blocks[0].text


def test_parse_xlsx():
    xlsx = FIXTURES / "maintenance_log.xlsx"
    if not xlsx.exists():
        return
    parser = DoclingParser()
    doc = parser.parse(xlsx, "maintenance_log.xlsx")
    assert len(doc.blocks) >= 3
    assert any("E-2047" in b.text for b in doc.blocks)


def test_chunker():
    settings = get_settings()
    parser = DoclingParser()
    chunker = Chunker(settings)
    doc = parser.parse(FIXTURES / "maintenance_log.txt", "maintenance_log.txt")
    chunks = chunker.split_document(doc, "default", ["motor"], "/tmp/log.txt")
    assert len(chunks) >= 1
    assert chunks[0].tenant_id == "default"


def test_chunker_preserves_document_structure():
    settings = get_settings()
    chunker = Chunker(settings)
    doc = ParsedDocument(
        source_file="manual.pdf",
        source_type=SourceType.PDF,
        blocks=[
            TextBlock(
                text=(
                    "# Controller not responding\n\n"
                    "Check the incoming power supply.\n\n"
                    "| Cause | Recommended action |\n"
                    "|---|---|\n"
                    "| Fuse tripped | Reset the fuse |"
                ),
                page_number=33,
                source_type=SourceType.PDF,
            )
        ],
    )

    chunks = chunker.split_document(doc, "default", [], "/tmp/manual.pdf")

    assert chunks
    assert all(chunk.page_number == 33 for chunk in chunks)
    assert all("Controller not responding" in chunk.text for chunk in chunks)
    assert any("| Cause | Recommended action |" in chunk.text for chunk in chunks)


def test_docling_parser_uses_page_numbers():
    class FakePage:
        def __init__(self, text):
            self.text = text

    class FakeDocument:
        pages = {4: FakePage("page four"), 9: FakePage("page nine")}

        def export_to_markdown(self):
            return "whole document fallback"

    class FakeResult:
        document = FakeDocument()

    parser = DoclingParser(pdf_ocr_mode="never")
    parser._converters[False] = type("FakeConverter", (), {"convert": lambda self, _: FakeResult()})()
    parsed = parser.parse(Path("manual.pdf"), "manual.pdf")

    assert [(block.page_number, block.text) for block in parsed.blocks] == [
        (4, "page four"),
        (9, "page nine"),
    ]


def test_rrf():
    dense = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
    sparse = [("b", 5.0), ("d", 4.0), ("a", 3.0)]
    fused = reciprocal_rank_fusion([dense, sparse])
    ids = [doc_id for doc_id, _ in fused]
    assert "b" in ids
    assert "a" in ids


def test_context_builder():
    settings = get_settings()
    builder = ContextBuilder(settings)
    chunk = Chunk.new(
        text="Motor overheating on M-42. Check coolant flow.",
        tenant_id="default",
        source_file="maintenance_log.txt",
        source_type=SourceType.TEXT,
        page_number=1,
        tags=["motor"],
        raw_file_url="/tmp/log.txt",
        chunk_index=0,
    )
    retrieved = [RetrievedChunk(chunk=chunk, rerank_score=2.5)]
    prompt, sources = builder.build("What caused overheating?", retrieved)
    assert "Motor overheating" in prompt
    assert len(sources) == 1
    assert builder.compute_confidence(retrieved) > 0


def test_greetings_do_not_trigger_clarification():
    assert _is_greeting("Hey")
    assert _is_greeting("hey there")
    assert _classify_query("hey") == "greeting"
    assert _classify_query("hello assistant") == "greeting"
    assert _classify_query("robot stopped at station 31") == "maintenance"
    assert not _needs_clarification("Hey")


def test_vague_manufacturing_query_gets_relevant_options():
    assert _needs_clarification("weld error")
    labels = [option.label for option in _clarification_options_for("weld error")]
    assert "Weld alarm or code" in labels
    assert "Weld quality issue" in labels


if __name__ == "__main__":
    test_parse_txt()
    test_parse_xlsx()
    test_chunker()
    test_rrf()
    test_context_builder()
    print("All smoke tests passed.")
