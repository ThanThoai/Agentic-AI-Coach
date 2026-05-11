from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedChunk:
    text: str
    doc_title: str
    section_title: str
    source_file: str
    chunk_index: str           # str to accommodate "2.1", "4+5" merged variants
    tags: list[str] = field(default_factory=list)
    difficulty: list[str] = field(default_factory=list)
    topic_type: str = ""


_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _extract_h1(text: str) -> str:
    m = _H1_RE.search(text)
    return m.group(1).strip() if m else Path("unknown").stem


def _split_by_h2(text: str) -> list[tuple[str, str]]:
    """Return list of (section_title, section_body) pairs."""
    h2_spans = [(m.start(), m.group(1).strip()) for m in _H2_RE.finditer(text)]

    if not h2_spans:
        # No H2 sections — entire body becomes one chunk
        return []

    sections: list[tuple[str, str]] = []

    # Content before the first H2 becomes a synthetic "Overview" section
    pre_h2 = text[: h2_spans[0][0]].strip()
    if pre_h2:
        # Strip H1 from the overview block
        pre_h2_clean = _H1_RE.sub("", pre_h2).strip()
        if pre_h2_clean:
            sections.append(("Overview", pre_h2_clean))

    for i, (start, title) in enumerate(h2_spans):
        end = h2_spans[i + 1][0] if i + 1 < len(h2_spans) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append((title, body))

    return sections


def parse_document(path: Path) -> list[ParsedChunk]:
    """Parse a single markdown file into ParsedChunk objects."""
    raw = path.read_text(encoding="utf-8")
    doc_title = _extract_h1(raw)
    source_file = path.name

    sections = _split_by_h2(raw)

    if not sections:
        # No H2 — entire file body as one chunk
        body = _H1_RE.sub("", raw).strip()
        if not body:
            return []
        return [
            ParsedChunk(
                text=body,
                doc_title=doc_title,
                section_title=doc_title,
                source_file=source_file,
                chunk_index="0",
            )
        ]

    chunks: list[ParsedChunk] = []
    for idx, (section_title, body) in enumerate(sections):
        if not body.strip():
            continue
        chunks.append(
            ParsedChunk(
                text=body,
                doc_title=doc_title,
                section_title=section_title,
                source_file=source_file,
                chunk_index=str(idx),
            )
        )
    return chunks


def parse_all(directory: Path) -> list[ParsedChunk]:
    """Parse every .md file in *directory* (non-recursive)."""
    chunks: list[ParsedChunk] = []
    for md_file in sorted(directory.glob("*.md")):
        chunks.extend(parse_document(md_file))
    return chunks
