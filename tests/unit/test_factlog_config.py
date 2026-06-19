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
