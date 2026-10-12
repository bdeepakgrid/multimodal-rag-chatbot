import logging
import re

from config.settings import Settings
from models.schemas import Chunk, ParsedDocument, SourceType

logger = logging.getLogger(__name__)

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        try:
            # spaCy bundles compiled extensions that may not yet support the
            # interpreter running the API. It improves segmentation but must
            # never prevent the rest of the diagnostics service from starting.
            import spacy

            _nlp = spacy.load("en_core_web_sm")
        except Exception as exc:
            logger.warning("spaCy unavailable; using regex sentence splitting: %s", exc)
            _nlp = None
    return _nlp


def _approx_tokens(text: str) -> int:
    return len(text.split())


class Chunker:
    def __init__(self, settings: Settings):
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap
        self.chars_per_token = 4

    def split_document(
        self,
        doc: ParsedDocument,
        tenant_id: str,
        tags: list[str],
        raw_file_url: str,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        chunk_index = 0

        for block in doc.blocks:
            if not block.text.strip():
                continue
            if doc.source_type in (SourceType.EXCEL, SourceType.CSV):
                chunks.append(
                    Chunk.new(
                        text=block.text,
                        tenant_id=tenant_id,
                        source_file=doc.source_file,
                        source_type=doc.source_type,
                        page_number=block.page_number,
                        tags=tags,
                        raw_file_url=raw_file_url,
                        chunk_index=chunk_index,
                    )
                )
                chunk_index += 1
            else:
                for text in self._split_text(block.text):
                    chunks.append(
                        Chunk.new(
                            text=text,
                            tenant_id=tenant_id,
                            source_file=doc.source_file,
                            source_type=doc.source_type,
                            page_number=block.page_number,
                            tags=tags,
                            raw_file_url=raw_file_url,
                            chunk_index=chunk_index,
                        )
                    )
                    chunk_index += 1
        return chunks

    def _split_text(self, text: str) -> list[str]:
        max_chars = self.chunk_size * self.chars_per_token
        overlap_chars = self.chunk_overlap * self.chars_per_token
        units = self._split_structured_units(text)
        if not units:
            return [text] if text.strip() else []

        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for unit in units:
            unit_len = len(unit)

            # Keep a heading/table/list block intact where possible. If one
            # block itself is too large, split it by sentences/words below.
            if unit_len > max_chars:
                if current:
                    chunks.append("\n\n".join(current).strip())
                    current = []
                    current_len = 0
                chunks.extend(self._split_oversized_unit(unit, max_chars, overlap_chars))
                continue

            if current_len + unit_len + 2 > max_chars and current:
                chunks.append("\n\n".join(current).strip())
                overlap_text = "\n\n".join(current)
                if len(overlap_text) > overlap_chars:
                    overlap_text = overlap_text[-overlap_chars:]
                current = [overlap_text] if overlap_text else []
                current_len = len(overlap_text)

            current.append(unit)
            current_len += unit_len + 2

        if current:
            chunks.append("\n\n".join(current).strip())
        return chunks

    def _split_structured_units(self, text: str) -> list[str]:
        """Split Markdown into semantic units before applying size limits.

        Headings are retained as context, while tables and consecutive list
        items stay together. This improves retrieval for manuals and reports
        without assuming every input is Markdown.
        """
        lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
        units: list[str] = []
        current: list[str] = []
        heading_stack: list[str] = []
        in_table = False

        def flush() -> None:
            nonlocal current
            value = "\n".join(current).strip()
            if value:
                heading = " > ".join(heading_stack)
                units.append(f"{heading}\n\n{value}" if heading else value)
            current = []

        for line in lines:
            stripped = line.strip()
            heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*$", stripped)
            is_table = stripped.startswith("|") and stripped.endswith("|")
            is_list = bool(re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)", stripped))

            if heading:
                flush()
                level = len(heading.group(1))
                heading_stack = heading_stack[: level - 1]
                heading_stack.append(stripped)
                in_table = False
                continue

            if not stripped:
                if in_table:
                    continue
                flush()
                continue

            if is_table:
                if not in_table and current:
                    flush()
                current.append(line)
                in_table = True
                continue

            if in_table:
                flush()
                in_table = False

            if is_list:
                current.append(line)
                continue

            if current and current[-1].lstrip().startswith(("- ", "* ", "+ ")):
                current.append(line)
                continue

            # Plain text paragraphs are collected until a blank line or a
            # structural marker; sentence splitting handles oversized ones.
            current.append(line)

        flush()
        return units

    def _split_oversized_unit(self, unit: str, max_chars: int, overlap_chars: int) -> list[str]:
        sentences = self._split_sentences(unit)
        if len(sentences) <= 1:
            words = unit.split()
            pieces = []
            current: list[str] = []
            current_len = 0
            for word in words:
                if current and current_len + len(word) + 1 > max_chars:
                    pieces.append(" ".join(current))
                    current = []
                    current_len = 0
                current.append(word)
                current_len += len(word) + 1
            if current:
                pieces.append(" ".join(current))
            return pieces

        pieces: list[str] = []
        current: list[str] = []
        current_len = 0
        for sentence in sentences:
            if current and current_len + len(sentence) + 1 > max_chars:
                pieces.append(" ".join(current).strip())
                overlap = " ".join(current)[-overlap_chars:] if overlap_chars else ""
                current = [overlap] if overlap else []
                current_len = len(overlap)
            current.append(sentence)
            current_len += len(sentence) + 1
        if current:
            pieces.append(" ".join(current).strip())
        return pieces

    def _split_sentences(self, text: str) -> list[str]:
        nlp = _get_nlp()
        if nlp:
            doc = nlp(text)
            return [sent.text.strip() for sent in doc.sents if sent.text.strip()]
        return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
