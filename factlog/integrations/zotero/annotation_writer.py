#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Format a Zotero item's highlights + notes into a ``sources/<stem>-notes.md``.

Phase 3 brings a researcher's PDF highlights and item notes into the KB as an
ordinary source, so the existing ``sync`` step (LLM extraction + the human accept
gate) turns them into candidate facts. The agent never writes candidates itself
(P1) — annotations are just richer source text.

The file pairs with the item's bibliographic ``<stem>.md`` by sharing the stem
and carries the same ``zotero_key`` in its front matter. Its content is a pure
function of the Zotero annotations/notes (no import timestamp), which lets it be
both idempotent and fresh:

* target absent            -> write it
* target is ours & same    -> skip (unchanged)
* target is ours & differs -> overwrite (a highlight was added/changed)
* target is NOT ours       -> skip (never clobber a user's own file — P4)

"ours" is detected by the ``source_kind: annotations`` marker in the front
matter. Writes are atomic (temp + os.replace).
"""
from __future__ import annotations

import html as _html
import os
import re
from dataclasses import dataclass
from pathlib import Path

from factlog.integrations.zotero.source_writer import _yaml_str  # reuse the escaper

_MARKER = "source_kind: annotations"
_HEAD_SCAN_BYTES = 512

_BR_RE = re.compile(r"(?i)<\s*br\s*/?>")
_BLOCK_CLOSE_RE = re.compile(r"(?i)</\s*(p|div|li|h[1-6]|tr)\s*>")
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class AnnotationResult:
    path: Path | None
    status: str  # "written" | "updated" | "skipped"
    reason: str = ""


def html_to_text(value: object) -> str:
    """Flatten Zotero note HTML to plain text, block tags becoming line breaks."""
    if not isinstance(value, str):
        return ""
    text = _BR_RE.sub("\n", value)
    text = _BLOCK_CLOSE_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _html.unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _ad(item: dict) -> dict:
    data = item.get("data") if isinstance(item, dict) else None
    return data if isinstance(data, dict) else {}


def _str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _format_highlight(data: dict) -> str:
    """One highlight block, or "" when it carries no text at all."""
    text = _str(data.get("annotationText"))
    comment = _str(data.get("annotationComment"))
    if not text and not comment:
        return ""
    page = _str(data.get("annotationPageLabel"))
    header = f"### p. {page}" if page else "###"
    parts = [header]
    if text:
        # Quote the highlighted passage; a multi-line passage stays inside the quote.
        parts.append("\n".join(f"> {line}" for line in text.splitlines()))
    if comment:
        parts.append(comment)
    return "\n\n".join(parts)


def render_annotations(parsed_bib: dict, annotations: list[dict], notes: list[dict]) -> str:
    """The full markdown (front matter + body), or "" if there is nothing to write."""
    highlight_blocks = [block for block in (_format_highlight(_ad(a)) for a in annotations) if block]
    note_texts = [t for t in (html_to_text(_ad(n).get("note")) for n in notes) if t]
    if not highlight_blocks and not note_texts:
        return ""

    title = parsed_bib.get("title") or "Untitled"
    lines = ["---"]
    lines.append(f"zotero_key: {_yaml_str(parsed_bib.get('zotero_key', ''))}")
    lines.append(f"title: {_yaml_str(title)}")
    lines.append("imported_from: zotero")
    lines.append(_MARKER)
    lines.append("---\n")
    lines.append(f"# Annotations — {title}\n")

    if highlight_blocks:
        lines.append("## Highlights\n")
        lines.append("\n\n".join(highlight_blocks))
        lines.append("")
    if note_texts:
        lines.append("## Notes\n")
        lines.append("\n\n".join(note_texts))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _is_ours(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as fh:
            head = fh.read(_HEAD_SCAN_BYTES)
    except OSError:
        return False
    return head.startswith("---") and _MARKER in head


def write_annotations(
    parsed_bib: dict,
    annotations: list[dict],
    notes: list[dict],
    base_stem: str,
    target: Path | str,
) -> AnnotationResult:
    """Write ``sources/<base_stem>-notes.md`` from the item's highlights/notes."""
    content = render_annotations(parsed_bib, annotations, notes)
    sources_dir = Path(target) / "sources"
    path = sources_dir / f"{base_stem}-notes.md"

    if not content:
        return AnnotationResult(None, "skipped", "no annotations or notes")

    if path.exists():
        if not _is_ours(path):
            return AnnotationResult(path, "skipped", "target exists and is not a zotero notes file")
        try:
            if path.read_text(encoding="utf-8") == content:
                return AnnotationResult(path, "skipped", "unchanged")
        except OSError:
            pass  # unreadable -> fall through and rewrite
        sources_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, content)
        return AnnotationResult(path, "updated")

    sources_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, content)
    return AnnotationResult(path, "written")


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
