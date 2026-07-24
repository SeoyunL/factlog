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


# --- CLI layer (`factlog zotero-search`) ---------------------------------------
from factlog import cli  # noqa: E402 - kept next to the CLI tests that use it


def _kb(tmp_path):
    (tmp_path / "sources").mkdir()
    return tmp_path


class FakeSearchClient:
    """A client whose search_items returns a fixed list, records the args, or raises."""

    def __init__(self, items=None, raise_exc=None):
        self._items = items or []
        self._raise = raise_exc
        self.calls: list[tuple] = []

    def search_items(self, q, qmode="titleCreatorYear", limit=None):
        self.calls.append((q, qmode, limit))
        if self._raise is not None:
            raise self._raise
        return list(self._items)


def _run(monkeypatch, argv, client):
    monkeypatch.setattr(cli, "_make_zotero_client", lambda config: client)
    return cli.main(argv)


class TestParser:
    def test_query_is_positional_and_routes_to_the_command(self):
        args = cli.build_parser().parse_args(["zotero-search", "protein folding"])
        assert args.query == "protein folding" and args.func is cli.cmd_zotero_search

    def test_qmode_defaults_to_title_creator_year(self):
        args = cli.build_parser().parse_args(["zotero-search", "x"])
        assert args.qmode == "titleCreatorYear"

    def test_qmode_rejects_an_unknown_mode(self):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(["zotero-search", "x", "--qmode", "fuzzy"])


class TestRun:
    def test_lists_key_itemtype_and_title(self, tmp_path, monkeypatch, capsys):
        kb = _kb(tmp_path)
        client = FakeSearchClient([PREPRINT, ARTICLE])
        rc = _run(monkeypatch, ["zotero-search", "neurosymbolic", "--target", str(kb)], client)
        out = capsys.readouterr().out
        assert rc == 0
        assert "Found 2 results" in out
        assert "[preprint] KH78JUPE" in out
        assert "[journalArticle] ABCD1234" in out
        assert "Protein folding" in out

    def test_forwards_qmode_and_limit_to_the_client(self, tmp_path, monkeypatch, capsys):
        kb = _kb(tmp_path)
        client = FakeSearchClient([PREPRINT])
        _run(monkeypatch, ["zotero-search", "folding", "--qmode", "everything",
                           "--limit", "7", "--target", str(kb)], client)
        assert client.calls == [("folding", "everything", 7)]

    def test_default_limit_is_the_policy_default(self, tmp_path, monkeypatch, capsys):
        kb = _kb(tmp_path)
        client = FakeSearchClient([PREPRINT])
        _run(monkeypatch, ["zotero-search", "x", "--target", str(kb)], client)
        assert client.calls == [("x", "titleCreatorYear", cli._ZOTERO_SEARCH_DEFAULT_LIMIT)]

    def test_zero_results_is_exit_0_not_an_error(self, tmp_path, monkeypatch, capsys):
        kb = _kb(tmp_path)
        rc = _run(monkeypatch, ["zotero-search", "no such thing", "--target", str(kb)],
                  FakeSearchClient([]))
        out = capsys.readouterr().out
        assert rc == 0
        assert "Found 0 results" in out

    def test_connection_failure_exits_2(self, tmp_path, monkeypatch, capsys):
        kb = _kb(tmp_path)
        client = FakeSearchClient(raise_exc=ZoteroConnectionError("not running"))
        rc = _run(monkeypatch, ["zotero-search", "x", "--target", str(kb)], client)
        assert rc == 2
        assert "not running" in capsys.readouterr().err

    def test_other_zotero_error_exits_1(self, tmp_path, monkeypatch, capsys):
        kb = _kb(tmp_path)
        client = FakeSearchClient(raise_exc=ZoteroError("request failed"))
        rc = _run(monkeypatch, ["zotero-search", "x", "--target", str(kb)], client)
        assert rc == 1
        assert "request failed" in capsys.readouterr().err

    def test_blank_query_is_rejected_before_touching_zotero(self, tmp_path, monkeypatch, capsys):
        kb = _kb(tmp_path)
        client = FakeSearchClient([PREPRINT])
        rc = _run(monkeypatch, ["zotero-search", "   ", "--target", str(kb)], client)
        assert rc == 1
        assert client.calls == []  # never reached the client
        assert "non-empty" in capsys.readouterr().err

    def test_out_of_range_limit_is_rejected(self, tmp_path, monkeypatch, capsys):
        kb = _kb(tmp_path)
        client = FakeSearchClient([PREPRINT])
        rc = _run(monkeypatch, ["zotero-search", "x", "--limit", "0", "--target", str(kb)], client)
        assert rc == 1
        assert client.calls == []
        assert "between 1 and" in capsys.readouterr().err

    def test_not_a_kb_exits_1(self, tmp_path, monkeypatch, capsys):
        # target with no sources/ -> _require_kb fails before touching Zotero.
        rc = _run(monkeypatch, ["zotero-search", "x", "--target", str(tmp_path)],
                  FakeSearchClient([PREPRINT]))
        assert rc == 1

    def test_porcelain_emits_result_and_found_rows(self, tmp_path, monkeypatch, capsys):
        kb = _kb(tmp_path)
        client = FakeSearchClient([PREPRINT, ARTICLE])
        rc = _run(monkeypatch, ["zotero-search", "x", "--porcelain", "--target", str(kb)], client)
        lines = capsys.readouterr().out.splitlines()
        assert rc == 0
        assert lines == [
            "result\t1\tKH78JUPE\tpreprint\tNeurosymbolic Value-Inspired AI (Why, What, and How)",
            "result\t2\tABCD1234\tjournalArticle\tProtein folding",
            "found\t2",
        ]

    def test_porcelain_zero_results_emits_only_found_zero(self, tmp_path, monkeypatch, capsys):
        kb = _kb(tmp_path)
        rc = _run(monkeypatch, ["zotero-search", "x", "--porcelain", "--target", str(kb)],
                  FakeSearchClient([]))
        assert rc == 0
        assert capsys.readouterr().out.splitlines() == ["found\t0"]
