from __future__ import annotations

import logging
from dataclasses import replace

import tiktoken

from app.rag.parser import ParsedChunk

logger = logging.getLogger("rag.chunker")

MIN_TOKENS = 50
MAX_TOKENS = 512
OVERLAP_TOKENS = 64

_ENCODER: tiktoken.Encoding | None = None


def _encoder() -> tiktoken.Encoding:
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    return _ENCODER


def token_count(text: str) -> int:
    return len(_encoder().encode(text))


def is_structured_content(text: str) -> bool:
    """Return True when 60%+ of lines are code fences, indented blocks, or table rows."""
    lines = text.strip().splitlines()
    if not lines:
        return False
    structured = sum(
        1 for line in lines
        if line.startswith("```") or line.startswith("    ") or line.startswith("|")
    )
    return structured / len(lines) > 0.6


def _split_oversized(chunk: ParsedChunk) -> list[ParsedChunk]:
    enc = _encoder()
    tokens = enc.encode(chunk.text)

    sub_chunks: list[ParsedChunk] = []
    start = 0
    sub_index = 0

    while start < len(tokens):
        end = min(start + MAX_TOKENS, len(tokens))
        window_text = enc.decode(tokens[start:end])
        sub_chunks.append(
            replace(
                chunk,
                text=window_text,
                chunk_index=f"{chunk.chunk_index}.{sub_index}",
            )
        )
        if end == len(tokens):
            break
        start = end - OVERLAP_TOKENS
        sub_index += 1

    return sub_chunks


def process_chunks(parsed: list[ParsedChunk]) -> list[ParsedChunk]:
    """Apply size guardrails and structured-content annotation to parsed chunks."""
    result: list[ParsedChunk] = []
    pending: ParsedChunk | None = None   # buffered short chunk waiting to merge

    stats = {"merged_short": 0, "split_long": 0, "structured": 0, "normal": 0}

    def _flush_with_next(short: ParsedChunk, nxt: ParsedChunk) -> ParsedChunk:
        merged_text = short.text + "\n\n" + nxt.text
        merged_title = f"{short.section_title} + {nxt.section_title}"
        merged_index = f"{short.chunk_index}+{nxt.chunk_index}"
        return replace(
            short,
            text=merged_text,
            section_title=merged_title,
            chunk_index=merged_index,
        )

    for chunk in parsed:
        tc = token_count(chunk.text)

        if pending is not None:
            # Merge the buffered short chunk with this one
            chunk = _flush_with_next(pending, chunk)
            pending = None
            tc = token_count(chunk.text)
            stats["merged_short"] += 1

        if tc < MIN_TOKENS:
            # Buffer and try to merge with next sibling
            pending = chunk
            continue

        if tc > MAX_TOKENS:
            sub = _split_oversized(chunk)
            result.extend(sub)
            stats["split_long"] += 1
            continue

        # Normal path
        stats["normal"] += 1
        result.append(chunk)

    if pending is not None:
        # Last chunk was short — merge backward with the previous result
        if result:
            prev = result.pop()
            merged = _flush_with_next(prev, pending)
            tc_merged = token_count(merged.text)
            if tc_merged > MAX_TOKENS:
                result.extend(_split_oversized(merged))
                stats["split_long"] += 1
            else:
                result.append(merged)
            stats["merged_short"] += 1
        else:
            # Only one chunk in the document and it was short — keep it
            result.append(pending)

    # Annotate structured content
    for chunk in result:
        if is_structured_content(chunk.text):
            stats["structured"] += 1

    logger.info(
        "chunker stats",
        total_parsed=len(parsed),
        **stats,
    )
    return result
