#!/usr/bin/env python3
"""Run a practical health and behavior evaluation for the RAG system.

Examples:
    .venv/bin/python scripts/evaluate_system.py
    .venv/bin/python scripts/evaluate_system.py --live
    .venv/bin/python scripts/evaluate_system.py --pdf /path/to/manual.pdf
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.warned = 0
        self.failed = 0

    def pass_(self, message: str) -> None:
        self.passed += 1
        print(f"PASS  {message}")

    def warn(self, message: str) -> None:
        self.warned += 1
        print(f"WARN  {message}")

    def fail(self, message: str) -> None:
        self.failed += 1
        print(f"FAIL  {message}")

    def summary(self) -> int:
        print(f"\nSummary: {self.passed} passed, {self.warned} warnings, {self.failed} failed")
        return 1 if self.failed else 0


def check_query_classification(report: Report) -> None:
    from api.routers.chat import _classify_query

    cases = {
        "hey": "greeting",
        "hello assistant": "greeting",
        "robot stopped at station 31": "maintenance",
        "what is the weather today": "out_of_scope",
    }
    for query, expected in cases.items():
        actual = _classify_query(query)
        if actual == expected:
            report.pass_(f"query classification: {query!r} -> {actual}")
        else:
            report.fail(f"query classification: {query!r} -> {actual}, expected {expected}")


def check_parsing_and_chunking(report: Report, pdf_path: Path | None) -> None:
    from config.settings import Settings
    from ingestion.chunker import Chunker
    from ingestion.parsers.docling_parser import DoclingParser
    from models.schemas import ParsedDocument, SourceType, TextBlock

    parser = DoclingParser()
    fixture = ROOT / "tests" / "fixtures" / "maintenance_log.txt"
    try:
        parsed = parser.parse(fixture, fixture.name)
        if parsed.blocks and "E-2047" in parsed.blocks[0].text:
            report.pass_("plain-text parsing")
        else:
            report.fail("plain-text parsing did not preserve fixture content")
    except Exception as exc:
        report.fail(f"plain-text parsing raised {type(exc).__name__}: {exc}")

    try:
        doc = ParsedDocument(
            source_file="evaluation.md",
            source_type=SourceType.PDF,
            blocks=[
                TextBlock(
                    "# Safety\n\nCheck power.\n\n| Cause | Action |\n|---|---|\n| Fuse | Reset |",
                    7,
                    SourceType.PDF,
                )
            ],
        )
        chunks = Chunker(Settings()).split_document(doc, "default", [], "")
        if chunks and all(chunk.page_number == 7 for chunk in chunks):
            report.pass_(f"structure-aware chunking ({len(chunks)} chunks, page preserved)")
        else:
            report.fail("chunking lost page metadata or produced no chunks")
    except Exception as exc:
        report.fail(f"chunking raised {type(exc).__name__}: {exc}")

    if not pdf_path:
        report.warn("no PDF supplied; skipped PDF text-layer and OCR preflight")
        return
    if not pdf_path.exists():
        report.fail(f"PDF does not exist: {pdf_path}")
        return

    try:
        ocr_enabled = parser._ocr_enabled(pdf_path)
        mode = "OCR enabled" if ocr_enabled else "OCR skipped; text layer detected"
        report.pass_(f"PDF preflight: {pdf_path.name} ({mode})")
    except Exception as exc:
        report.fail(f"PDF preflight raised {type(exc).__name__}: {exc}")


def check_feedback(report: Report) -> None:
    from storage.feedback_store import FeedbackStore

    with tempfile.TemporaryDirectory(prefix="rag-eval-") as temp_dir:
        db_path = Path(temp_dir) / "feedback.sqlite3"
        store = FeedbackStore(db_path)
        store.save_pending("eval-session", "default", "robot heat", "chunk-a", "MX-1", "manual.pdf")
        restarted = FeedbackStore(db_path)
        pending = restarted.get_pending("eval-session")
        if pending and pending["chunk_id"] == "chunk-a":
            report.pass_("feedback pending state survives restart")
        else:
            report.fail("feedback pending state was not restored")

        restarted.record_event("default", "eval-session", "robot heat", "confirmed", "chunk-a", "MX-1", "manual.pdf")
        restarted.record_event("default", "eval-session", "robot heat", "rejected", "chunk-b", "MX-2", "manual.pdf")
        scores = restarted.get_chunk_scores({"default"})
        if scores.get(("default", "chunk-a")) == 1.0 and scores.get(("default", "chunk-b")) == -1.0:
            report.pass_("feedback produces positive and negative ranking signals")
        else:
            report.fail(f"unexpected feedback ranking signals: {scores}")


def check_live_services(report: Report) -> None:
    from config.settings import get_settings

    settings = get_settings()
    endpoints = {
        "Ollama": f"{settings.ollama_base_url.rstrip('/')}/api/tags",
        "Qdrant": f"{settings.qdrant_url.rstrip('/')}/collections",
    }
    for name, url in endpoints.items():
        try:
            with urlopen(url, timeout=5) as response:
                if response.status == 200:
                    report.pass_(f"{name} reachable")
                else:
                    report.fail(f"{name} returned HTTP {response.status}")
        except (OSError, URLError) as exc:
            report.fail(f"{name} unreachable at {url}: {exc}")


def run_tests(report: Report) -> None:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_smoke.py",
        "tests/test_feedback.py",
        "tests/test_chat_selection_regression.py",
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if result.returncode == 0:
        last_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "tests passed"
        report.pass_(f"focused regression tests: {last_line}")
    else:
        report.fail("focused regression tests failed")
        print(result.stdout)
        print(result.stderr)


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--live", action="store_true", help="check Ollama and Qdrant HTTP health")
    cli.add_argument("--pdf", type=Path, help="run PDF text-layer/OCR preflight")
    args = cli.parse_args()

    report = Report()
    print("Multimodal RAG system evaluation\n")
    check_query_classification(report)
    check_parsing_and_chunking(report, args.pdf)
    check_feedback(report)
    run_tests(report)
    if args.live:
        check_live_services(report)
    else:
        report.warn("live service checks skipped; rerun with --live")
    return report.summary()


if __name__ == "__main__":
    raise SystemExit(main())

