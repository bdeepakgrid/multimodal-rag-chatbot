import csv
import logging
import subprocess
from pathlib import Path
from typing import Optional

from models.schemas import ParsedDocument, SourceType, TextBlock

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".csv", ".txt", ".md"}


class DoclingParser:
    def __init__(self, pdf_ocr_mode: str = "auto"):
        self._converters = {}
        self.pdf_ocr_mode = pdf_ocr_mode

    def _get_converter(self, file_path: Path | None = None):
        ocr_enabled = self._ocr_enabled(file_path)
        if ocr_enabled not in self._converters:
            from docling.document_converter import DocumentConverter

            if file_path is not None and file_path.suffix.lower() == ".pdf":
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import PdfPipelineOptions
                from docling.document_converter import PdfFormatOption

                options = PdfPipelineOptions(do_ocr=ocr_enabled)
                self._converters[ocr_enabled] = DocumentConverter(
                    format_options={
                        InputFormat.PDF: PdfFormatOption(pipeline_options=options),
                    }
                )
            else:
                self._converters[ocr_enabled] = DocumentConverter()
        return self._converters[ocr_enabled]

    def _ocr_enabled(self, file_path: Path | None) -> bool:
        """Use OCR only when a PDF appears to need it.

        Text-layer PDFs can contain diagrams, but running OCR over every image
        in them is unnecessarily slow and produces noisy empty-result logs.
        A mostly scanned PDF still gets OCR automatically.
        """
        mode = self.pdf_ocr_mode
        if mode == "always" or file_path is None or file_path.suffix.lower() != ".pdf":
            return mode == "always"
        if mode == "never":
            return False

        try:
            from pypdf import PdfReader

            reader = PdfReader(str(file_path))
            if not reader.pages:
                return False
            sample = reader.pages[: min(len(reader.pages), 30)]
            text_pages = sum(bool((page.extract_text() or "").strip()) for page in sample)
            return text_pages / len(sample) < 0.9
        except Exception:
            # Poppler is already used by the PDF tooling on macOS/Linux and
            # gives us a dependency-free fallback for the same preflight.
            try:
                output = subprocess.run(
                    ["pdftotext", "-f", "1", "-l", "30", str(file_path), "-"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
                pages = [page.strip() for page in output.split("\f")]
                if pages:
                    text_pages = sum(bool(page) for page in pages)
                    return text_pages / len(pages) < 0.9
            except (OSError, subprocess.SubprocessError):
                pass

            # If neither preflight tool is available, preserve the prior
            # behavior so a scanned document is not silently ingested without
            # its text.
            logger.warning("Could not inspect PDF text layer; keeping OCR enabled")
            return True

    def parse(self, file_path: Path, source_file: str) -> ParsedDocument:
        suffix = file_path.suffix.lower()
        source_type = self._detect_source_type(suffix)

        if suffix in {".csv", ".xlsx", ".xls"}:
            return self._parse_tabular(file_path, source_file, source_type)
        if suffix in {".txt", ".md"}:
            return self._parse_plain_text(file_path, source_file)
        return self._parse_docling(file_path, source_file, source_type)

    def _detect_source_type(self, suffix: str) -> SourceType:
        mapping = {
            ".pdf": SourceType.PDF,
            ".docx": SourceType.DOCX,
            ".xlsx": SourceType.EXCEL,
            ".xls": SourceType.EXCEL,
            ".csv": SourceType.CSV,
            ".txt": SourceType.TEXT,
            ".md": SourceType.TEXT,
        }
        return mapping.get(suffix, SourceType.TEXT)

    def _parse_plain_text(self, file_path: Path, source_file: str) -> ParsedDocument:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        blocks = [TextBlock(text=text.strip(), page_number=None, source_type=SourceType.TEXT)]
        return ParsedDocument(source_file=source_file, source_type=SourceType.TEXT, blocks=blocks)

    def _parse_tabular(self, file_path: Path, source_file: str, source_type: SourceType) -> ParsedDocument:
        suffix = file_path.suffix.lower()
        blocks: list[TextBlock] = []

        if suffix == ".csv":
            with open(file_path, newline="", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                for row_idx, row in enumerate(reader, start=1):
                    parts = [f"{h}: {row.get(h, '')}" for h in headers]
                    row_text = " | ".join(parts)
                    blocks.append(
                        TextBlock(text=row_text, page_number=row_idx, source_type=source_type)
                    )
            return ParsedDocument(source_file=source_file, source_type=source_type, blocks=blocks)

        import openpyxl

        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)

        # First pass: read every sheet into (headers, rows) so we can reason
        # about the workbook as a whole before deciding what to chunk. A
        # workbook frequently has one primary content sheet plus reference
        # sheets (glossaries, column dictionaries) and/or a near-duplicate
        # "metadata" sheet that restates the same records — none of that
        # should get chunked and searched as if it were independent content.
        sheets: list[dict] = []
        for sheet in wb.worksheets:
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                continue
            headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
            data_rows = rows[1:]
            sheets.append({"name": sheet.title, "headers": headers, "rows": data_rows})

        reference_sheets = {s["name"] for s in sheets if self._is_reference_sheet(s["headers"], s["name"])}
        if reference_sheets:
            logger.info(
                "Skipping reference/glossary sheet(s) in %s: %s (definitional content, not incident data)",
                source_file,
                ", ".join(sorted(reference_sheets)),
            )

        content_sheets = [s for s in sheets if s["name"] not in reference_sheets]

        # Second pass: build row text per remaining sheet, then drop rows
        # that are near-duplicates of a row already emitted from another
        # sheet sharing the same key value (e.g. a "RAG_Metadata" sheet that
        # restates every incident from the primary sheet under the same ID).
        seen_by_key: dict[str, str] = {}  # key value -> sheet name that already emitted it
        page_counter = 0

        for sheet_info in content_sheets:
            headers = sheet_info["headers"]
            key_idx = self._guess_key_column(headers)

            for row in sheet_info["rows"]:
                parts = []
                for h, val in zip(headers, row):
                    if val is not None and str(val).strip():
                        parts.append(f"{h}: {val}")
                if not parts:
                    continue
                row_text = " | ".join(parts)

                if key_idx is not None and key_idx < len(row) and row[key_idx] is not None:
                    key_val = str(row[key_idx]).strip()
                    if key_val:
                        prior_sheet = seen_by_key.get(key_val)
                        if prior_sheet is not None:
                            logger.info(
                                "Skipping duplicate record '%s' in sheet '%s' of %s "
                                "(already captured from sheet '%s')",
                                key_val,
                                sheet_info["name"],
                                source_file,
                                prior_sheet,
                            )
                            continue
                        seen_by_key[key_val] = sheet_info["name"]

                page_counter += 1
                blocks.append(
                    TextBlock(
                        text=f"[Sheet: {sheet_info['name']}] {row_text}",
                        page_number=page_counter,
                        source_type=source_type,
                    )
                )

        return ParsedDocument(source_file=source_file, source_type=source_type, blocks=blocks)

    def _is_reference_sheet(self, headers: list[str], sheet_name: str) -> bool:
        """Heuristic for glossary/data-dictionary style sheets: they describe
        the *schema* (column names, allowed values, controlled terms) rather
        than containing actual records to search over."""
        name_lower = sheet_name.lower()
        if any(kw in name_lower for kw in ("dictionary", "taxonomy", "glossary", "legend", "readme", "definitions")):
            return True

        header_text = " ".join(h.lower() for h in headers)
        definitional_markers = ("definition", "allowed values", "controlled term", "expected data type")
        return any(marker in header_text for marker in definitional_markers)

    def _guess_key_column(self, headers: list[str]) -> Optional[int]:
        """Find a column that looks like a stable record identifier (e.g.
        'Incident_ID'), used to detect the same record appearing again in a
        different sheet under different column names."""
        for i, h in enumerate(headers):
            h_lower = h.lower()
            if h_lower.endswith("_id") or h_lower == "id":
                return i
        return None

    def _parse_docling(self, file_path: Path, source_file: str, source_type: SourceType) -> ParsedDocument:
        converter = self._get_converter(file_path)
        result = converter.convert(str(file_path))
        doc = result.document
        blocks: list[TextBlock] = []

        # Docling exposes pages as either a list or a page-number keyed
        # mapping depending on its version. Prefer page-level export so
        # retrieval citations refer to the real PDF page.
        pages = getattr(doc, "pages", None)
        if pages:
            page_items = pages.items() if hasattr(pages, "items") else enumerate(pages, start=1)
            for page_no, page in page_items:
                try:
                    page_text = doc.export_to_markdown(page_no=int(page_no))
                except (TypeError, AttributeError):
                    page_text = self._export_page(page)
                if page_text.strip():
                    blocks.append(
                        TextBlock(
                            text=page_text.strip(),
                            page_number=int(page_no),
                            source_type=source_type,
                        )
                    )

        # DOCX and older Docling versions may not expose page objects. Keep
        # a document-level fallback for those cases instead of dropping text.
        if not blocks:
            markdown = doc.export_to_markdown()
            if markdown.strip():
                blocks.append(
                    TextBlock(text=markdown.strip(), page_number=None, source_type=source_type)
                )

        if not blocks:
            blocks.append(TextBlock(text="", page_number=None, source_type=source_type))

        return ParsedDocument(source_file=source_file, source_type=source_type, blocks=blocks)

    def _export_page(self, page) -> str:
        if hasattr(page, "export_to_markdown"):
            return page.export_to_markdown() or ""
        if hasattr(page, "text"):
            return page.text or ""
        return str(page) if page else ""
