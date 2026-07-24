# SPDX-License-Identifier: Apache-2.0
"""Unit tests for Zotero discovery search (#455).

Two layers share this file: the client method :meth:`ZoteroClient.search_items`
(below) and the ``zotero-search`` CLI command (further down). Both use a fake
backend so they stay deterministic and pyzotero-free, mirroring
``test_zotero_client.py``'s convention — a minimal stand-in that records the
kwargs it was called with, so an assertion can prove ``q``/``qmode``/``limit``
reached the API unchanged.
"""
from __future__ import annotations

import pytest

from factlog.integrations.zotero.api_client import (
    ZoteroClient,
    ZoteroConnectionError,
    ZoteroError,
)
from factlog.integrations.zotero.config import ZoteroConfig


PREPRINT = {
    "key": "KH78JUPE",
    "data": {
        "key": "KH78JUPE",
        "itemType": "preprint",
        "title": "Neurosymbolic Value-Inspired AI (Why, What, and How)",
    },
}
ARTICLE = {
    "key": "ABCD1234",
    "data": {"key": "ABCD1234", "itemType": "journalArticle", "title": "Protein folding"},
}
ATTACHMENT = {"key": "ATT1", "data": {"key": "ATT1", "itemType": "attachment", "title": "PDF"}}
NOTE = {"key": "NOTE1", "data": {"key": "NOTE1", "itemType": "note"}}


class ConnectError(Exception):  # httpx.ConnectError name — _classify routes by MRO name
    pass


class FakeBackend:
    """Minimal pyzotero stand-in for search: records the items() kwargs, or raises."""

    def __init__(self, items=None, exc=None):
        self._items = items or []
        self._exc = exc
        self.calls: list[dict] = []

    def items(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return list(self._items)


def _client(**kw):
    return ZoteroClient(ZoteroConfig(), backend=FakeBackend(**kw))


class TestSearchItems:
    def test_returns_bibliographic_items_only(self):
        client = _client(items=[PREPRINT, ATTACHMENT, NOTE, ARTICLE])
        results = client.search_items("neurosymbolic")
        keys = [r["data"]["key"] for r in results]
        assert keys == ["KH78JUPE", "ABCD1234"]

    def test_passes_query_and_default_qmode(self):
        backend = FakeBackend(items=[PREPRINT])
        client = ZoteroClient(ZoteroConfig(), backend=backend)
        client.search_items("protein folding")
        assert backend.calls == [{"q": "protein folding", "qmode": "titleCreatorYear"}]

    def test_forwards_qmode_and_limit(self):
        backend = FakeBackend(items=[PREPRINT])
        client = ZoteroClient(ZoteroConfig(), backend=backend)
        client.search_items("folding", qmode="everything", limit=5)
        assert backend.calls == [{"q": "folding", "qmode": "everything", "limit": 5}]

    def test_omits_limit_when_none(self):
        # None must not become an explicit limit= kwarg — the API keeps its own default.
        backend = FakeBackend(items=[])
        client = ZoteroClient(ZoteroConfig(), backend=backend)
        client.search_items("anything", limit=None)
        assert "limit" not in backend.calls[0]

    def test_empty_result_is_returned_not_an_error(self):
        # A successful search that matched nothing is an honest empty list, distinct
        # from a connection failure (which raises) — the CLI relies on this split.
        assert _client(items=[]).search_items("no such thing") == []

    @pytest.mark.parametrize("q", ["", "   ", "\t\n"])
    def test_blank_query_is_rejected_before_any_request(self, q):
        backend = FakeBackend(items=[PREPRINT])
        client = ZoteroClient(ZoteroConfig(), backend=backend)
        with pytest.raises(ZoteroError):
            client.search_items(q)
        assert backend.calls == []  # nothing was sent

    def test_does_not_page_with_everything(self):
        # A search is a bounded top-N; it must issue exactly one items() call and
        # never follow pagination (which would return the whole library past --limit).
        backend = FakeBackend(items=[PREPRINT, ARTICLE])
        client = ZoteroClient(ZoteroConfig(), backend=backend)
        client.search_items("x", limit=2)
        assert len(backend.calls) == 1

    def test_connection_failure_raises_connection_error(self):
        client = _client(items=[PREPRINT], exc=ConnectError("refused"))
        with pytest.raises(ZoteroConnectionError):
            client.search_items("neurosymbolic")
