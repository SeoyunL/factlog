# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the shared prepass resolver (#107)."""
from __future__ import annotations

import factlog_config


class TestResolveRootFromArgv:
    def test_reads_wiki_flag(self, monkeypatch, tmp_path):
        monkeypatch.setattr("sys.argv", ["tool", "--wiki", str(tmp_path), "extra", "args"])
        monkeypatch.delenv("FACTLOG_ROOT", raising=False)
        assert factlog_config.resolve_root_from_argv("--wiki") == str(tmp_path.resolve())

    def test_reads_target_flag(self, monkeypatch, tmp_path):
        monkeypatch.setattr("sys.argv", ["tool", "evaluate", "q?", "--target", str(tmp_path)])
        monkeypatch.delenv("FACTLOG_ROOT", raising=False)
        assert factlog_config.resolve_root_from_argv("--target") == str(tmp_path.resolve())

    def test_falls_back_to_env_when_flag_absent(self, monkeypatch, tmp_path):
        monkeypatch.setattr("sys.argv", ["tool", "somecmd"])
        monkeypatch.setenv("FACTLOG_ROOT", str(tmp_path))
        assert factlog_config.resolve_root_from_argv("--wiki") == str(tmp_path.resolve())

    def test_ignores_unrelated_args(self, monkeypatch, tmp_path):
        # parse_known_args must not choke on flags it doesn't define.
        monkeypatch.setattr("sys.argv", ["tool", "--strict", "--wiki", str(tmp_path), "--all"])
        monkeypatch.delenv("FACTLOG_ROOT", raising=False)
        assert factlog_config.resolve_root_from_argv("--wiki") == str(tmp_path.resolve())


class TestLangConfig:
    """read_lang / write_lang and their interaction with root (#269).

    Every test isolates XDG_CONFIG_HOME to a throwaway dir so the developer's real
    ~/.config/factlog/config.json is never read or written.
    """

    def _isolate(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    def test_read_lang_none_when_no_config(self, monkeypatch, tmp_path):
        self._isolate(monkeypatch, tmp_path)
        assert factlog_config.read_lang() is None

    def test_write_then_read_lang(self, monkeypatch, tmp_path):
        self._isolate(monkeypatch, tmp_path)
        factlog_config.write_lang("ko")
        assert factlog_config.read_lang() == "ko"

    def test_write_lang_trims_whitespace(self, monkeypatch, tmp_path):
        self._isolate(monkeypatch, tmp_path)
        factlog_config.write_lang("  en  ")
        assert factlog_config.read_lang() == "en"

    def test_write_lang_none_clears(self, monkeypatch, tmp_path):
        self._isolate(monkeypatch, tmp_path)
        factlog_config.write_lang("ko")
        factlog_config.write_lang(None)
        assert factlog_config.read_lang() is None

    def test_write_lang_empty_clears(self, monkeypatch, tmp_path):
        self._isolate(monkeypatch, tmp_path)
        factlog_config.write_lang("ko")
        factlog_config.write_lang("   ")
        assert factlog_config.read_lang() is None

    def test_write_lang_preserves_root(self, monkeypatch, tmp_path):
        self._isolate(monkeypatch, tmp_path)
        kb = tmp_path / "kb"
        kb.mkdir()
        factlog_config.write_root(kb)
        factlog_config.write_lang("ko")
        assert factlog_config.read_root() == str(kb.resolve())
        assert factlog_config.read_lang() == "ko"

    def test_write_root_preserves_lang(self, monkeypatch, tmp_path):
        self._isolate(monkeypatch, tmp_path)
        factlog_config.write_lang("ko")
        kb = tmp_path / "kb"
        kb.mkdir()
        factlog_config.write_root(kb)
        # Re-pointing the active KB must not drop the configured language.
        assert factlog_config.read_lang() == "ko"
        assert factlog_config.read_root() == str(kb.resolve())

    def test_root_only_config_backward_compat(self, monkeypatch, tmp_path):
        # A pre-#269 config ({"root": ...}, no lang) reads back as lang=None with
        # root intact — no regression for KBs set up before this feature.
        self._isolate(monkeypatch, tmp_path)
        cfg = factlog_config.config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        kb = tmp_path / "kb"
        kb.mkdir()
        cfg.write_text('{"root": "%s"}\n' % kb.resolve(), encoding="utf-8")
        assert factlog_config.read_lang() is None
        assert factlog_config.read_root() == str(kb.resolve())

    def test_broken_config_reads_none(self, monkeypatch, tmp_path):
        self._isolate(monkeypatch, tmp_path)
        cfg = factlog_config.config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("{ this is not json", encoding="utf-8")
        assert factlog_config.read_lang() is None
        assert factlog_config.read_root() is None

    def test_non_string_lang_reads_none(self, monkeypatch, tmp_path):
        self._isolate(monkeypatch, tmp_path)
        cfg = factlog_config.config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('{"root": "/x", "lang": 42}\n', encoding="utf-8")
        assert factlog_config.read_lang() is None
