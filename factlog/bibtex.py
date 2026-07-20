#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Turn a factlog source's front matter into a BibTeX entry.

`factlog export --bibtex` reads the provenance factlog already records in each
source's YAML front matter (written by the Zotero import) and emits BibTeX so a
researcher can cite factlog-tracked sources in LaTeX/Word. Read-only, no new
dependency — a small parser handles the simple YAML subset factlog writes.
"""
from __future__ import annotations

import re
from pathlib import Path

from factlog.export_types import resolve_source_type, should_promote_to_journal_type

_LIST_ITEM_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_KV_RE = re.compile(r"^([A-Za-z0-9_]+):\s*(.*)$")

# Work type -> BibTeX entry type; anything else falls back to @misc. Keyed by
# both vocabularies `resolve_source_type` can return: Zotero's camelCase
# itemType and OpenAlex's hyphenated work type. The two never collide — where
# they share a spelling ("book", "report", "preprint") they also share a meaning.
_ENTRY_TYPES = {
    # Zotero itemType
    "journalArticle": "article",
    "magazineArticle": "article",
    "newspaperArticle": "article",
    "conferencePaper": "inproceedings",
    "book": "book",
    "bookSection": "incollection",
    "encyclopediaArticle": "incollection",
    "dictionaryEntry": "incollection",
    "report": "techreport",
    "thesis": "phdthesis",
    "preprint": "misc",
    # OpenAlex work type (a subset of api_client.WORK_TYPES; see
    # tests/unit/test_export_entry_types.py, which pins that containment)
    "article": "article",
    "review": "article",
    "book-review": "article",
    "letter": "article",
    "editorial": "article",
    "erratum": "article",
    "retraction": "article",
    "data-paper": "article",
    "conference-paper": "inproceedings",
    "book-chapter": "incollection",
    "book-section": "incollection",
    "reference-entry": "incollection",
    "dissertation": "phdthesis",
    "report-component": "techreport",
    # Standard BibTeX has no @dataset/@software (those are biblatex), so these
    # stay @misc — but CSL does have them, hence no matching _CSL_TYPES value.
    "dataset": "misc",
    "software": "misc",
}

# Char-by-char LaTeX escaping (one pass, so inserted braces are not re-escaped).
_ESC = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "{": r"\{",
    "}": r"\}",
}


_SIMPLE_UNESCAPE = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _unescape(value: str) -> str:
    """Reverse the YAML scalar escaping factlog writes (\\n, \\t, \\", \\xNN)."""
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            if nxt in _SIMPLE_UNESCAPE:
                out.append(_SIMPLE_UNESCAPE[nxt])
                i += 2
                continue
            if nxt == "x" and i + 3 < len(value):
                try:
                    out.append(chr(int(value[i + 2 : i + 4], 16)))
                    i += 4
                    continue
                except ValueError:
                    pass
        out.append(ch)
        i += 1
    return "".join(out)


def _parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [_unescape(m) for m in _LIST_ITEM_RE.findall(raw)]
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return _unescape(raw[1:-1])
    if raw in ("true", "false"):
        return raw == "true"
    return raw


def parse_front_matter(text: str) -> dict:
    """Parse the leading ``---`` fenced YAML block into a dict ({} if none)."""
    if not text.startswith("---"):
        return {}
    rest = text[3:]
    end = rest.find("\n---")
    block = rest if end == -1 else rest[:end]
    fm: dict = {}
    for line in block.splitlines():
        match = _KV_RE.match(line.strip())
        if match:
            fm[match.group(1)] = _parse_value(match.group(2))
    return fm


def read_front_matter(path: Path | str) -> dict:
    try:
        head = Path(path).read_text(encoding="utf-8")[:4096]
    except OSError:
        return {}
    return parse_front_matter(head)


def is_annotation_source(fm: dict) -> bool:
    """True for a companion ``<stem>-notes.md`` (exported separately, if at all)."""
    return fm.get("source_kind") == "annotations"


def _entry_type(fm: dict) -> str:
    source_type = resolve_source_type(fm)
    if should_promote_to_journal_type(fm, source_type):
        # PubMed declares no type at all; naming a journal is the only evidence
        # its front matter gives that the record is a journal article (#384).
        return "article"
    return _ENTRY_TYPES.get(source_type, "misc") if source_type else "misc"


def _esc(value: str) -> str:
    return "".join(_ESC.get(ch, ch) for ch in value)


def safe_cite_key(value: str) -> str:
    """A BibTeX-safe citation key: keep ASCII word chars and '-', collapse rest."""
    key = re.sub(r"[^A-Za-z0-9\-]+", "-", value).strip("-")
    return key or "ref"


def to_bibtex(fm: dict, cite_key: str) -> str:
    """Render one BibTeX entry from a source's front-matter dict."""
    fields: list[tuple[str, str]] = []
    authors = fm.get("authors")
    if isinstance(authors, list) and authors:
        fields.append(("author", " and ".join(str(a) for a in authors)))
    entry_type = _entry_type(fm)
    # Standard BibTeX's @misc has no `journal` field: biber/BibTeX drops it with
    # a warning, which is how a published preprint lost its venue entirely (#384).
    # The venue is still worth recording, so it goes to `howpublished`, the field
    # @misc does define. Retyping the entry instead would contradict #60 — an
    # arXiv deposit stays a preprint even once `journal` names where it landed.
    venue_key = "journal" if entry_type != "misc" else "howpublished"
    for fm_key, bib_key in (("title", "title"), ("year", "year"),
                            ("journal", venue_key), ("doi", "doi")):
        value = fm.get(fm_key)
        if value:
            fields.append((bib_key, str(value)))
    if fm.get("pmid"):
        fields.append(("note", f"PMID: {fm['pmid']}"))

    lines = [f"@{entry_type}{{{safe_cite_key(cite_key)},"]
    for name, value in fields:
        lines.append(f"  {name} = {{{_esc(value)}}},")
    lines.append("}")
    return "\n".join(lines) + "\n"
