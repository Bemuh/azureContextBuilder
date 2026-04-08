"""Tests for story_context/cli.py

Mocks ADO at the ado_request level (I1 decision).
"""
from __future__ import annotations

import json
import os
import pytest
from unittest.mock import MagicMock, patch

from story_context.cli import main, _parse_ids, build_parser
from story_context.config import StoryContextError
import story_context.config as cfg
import story_context.ado as ado_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status: int, body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


def _patch_profile(monkeypatch, profile_name: str = "test") -> None:
    """Bypass profile loading and key checking."""
    monkeypatch.setattr(
        "story_context.config.get_profile",
        lambda name, profiles_file=None: {
            "name": profile_name,
            "org": "testorg",
            "project": "testproject",
            "area_path": "Proj\\Area",
            "iteration_path": "Proj\\Sprint 01",
        },
    )
    monkeypatch.setattr(ado_mod, "check_keys", lambda: None)


def _write_corpus(data_root: str, profile: str, story_id: int,
                  title: str = "Test Story") -> None:
    story_dir = os.path.join(data_root, "corpus", profile, str(story_id))
    os.makedirs(story_dir, exist_ok=True)
    story_md = f"# [{story_id}] {title}\n\n## Description\n\nContent.\n"
    with open(os.path.join(story_dir, "story.md"), "w") as fh:
        fh.write(story_md)
    meta = {"story_id": story_id, "fetched_at": "2026-04-06T15:00:00Z", "conversions": []}
    with open(os.path.join(story_dir, "refresh_meta.json"), "w") as fh:
        json.dump(meta, fh)


def _write_registry(data_root: str, profile: str, entries: dict) -> None:
    """Write a minimal registry YAML."""
    import yaml
    reg_dir = os.path.join(data_root, "registries")
    os.makedirs(reg_dir, exist_ok=True)
    reg = {
        "profile": profile,
        "created_at": "2026-04-06T14:00:00Z",
        "updated_at": "2026-04-06T14:00:00Z",
        "entries": entries,
    }
    with open(os.path.join(reg_dir, f"{profile}.yml"), "w") as fh:
        yaml.safe_dump(reg, fh, sort_keys=False)


# ---------------------------------------------------------------------------
# _parse_ids
# ---------------------------------------------------------------------------

def test_parse_ids_basic():
    assert _parse_ids("123,456,789") == [123, 456, 789]


def test_parse_ids_deduplicates():
    assert _parse_ids("123,123,456") == [123, 456]


def test_parse_ids_strips_whitespace():
    assert _parse_ids(" 123 , 456 ") == [123, 456]


def test_parse_ids_invalid_raises():
    with pytest.raises(Exception):
        _parse_ids("abc,123")


# ---------------------------------------------------------------------------
# No command → print help
# ---------------------------------------------------------------------------

def test_no_command_prints_help(capsys, monkeypatch):
    _patch_profile(monkeypatch)
    ret = main([])
    assert ret == 1


# ---------------------------------------------------------------------------
# list-stories
# ---------------------------------------------------------------------------

def test_list_stories_tsv_format(capsys, monkeypatch, tmp_path):
    _patch_profile(monkeypatch)
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))

    def fake_ado_request(url, method="GET", payload=None, **kwargs):
        if method == "POST":
            return _mock_response(200, {"workItems": [{"id": 101}]})
        return _mock_response(200, {"value": [
            {"id": 101, "fields": {
                "System.Title": "Story A",
                "System.WorkItemType": "User Story",
                "System.State": "Active",
                "System.AreaPath": "Proj\\Area",
                "System.IterationPath": "Proj\\Sprint 01",
            }},
        ]})

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        ret = main(["list-stories", "--profile", "test",
                     "--area", "Proj\\Area", "--iteration", "Proj\\Sprint 01"])

    assert ret == 0
    output = capsys.readouterr().out
    assert "Story A" in output
    assert "\t" in output  # TSV format


def test_list_stories_json_format(capsys, monkeypatch, tmp_path):
    _patch_profile(monkeypatch)
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))

    def fake_ado_request(url, method="GET", payload=None, **kwargs):
        if method == "POST":
            return _mock_response(200, {"workItems": [{"id": 101}]})
        return _mock_response(200, {"value": [
            {"id": 101, "fields": {"System.Title": "Story A", "System.WorkItemType": "User Story",
                                   "System.State": "Active", "System.AreaPath": "P\\A",
                                   "System.IterationPath": "P\\S"}},
        ]})

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        ret = main(["list-stories", "--profile", "test",
                     "--area", "P\\A", "--iteration", "P\\S", "--format", "json"])

    assert ret == 0
    output = capsys.readouterr().out
    parsed = json.loads(output)
    assert isinstance(parsed, list)


def test_list_stories_with_parent_epic_flag(capsys, monkeypatch, tmp_path):
    _patch_profile(monkeypatch)
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    captured_query: list[str] = []

    def fake_ado_request(url, method="GET", payload=None, **kwargs):
        if method == "POST":
            captured_query.append(payload["query"])
            return _mock_response(200, {"workItems": []})
        return _mock_response(200, {"value": []})

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        main(["list-stories", "--profile", "test",
              "--area", "A", "--iteration", "I", "--parent-epic", "500"])

    assert len(captured_query) == 1
    assert "System.Parent" in captured_query[0]
    assert "500" in captured_query[0]


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

def test_register_parses_ids(capsys, monkeypatch, tmp_path):
    _patch_profile(monkeypatch)
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))

    def fake_ado_request(url, method="GET", **kwargs):
        return _mock_response(200, {"value": [
            {"id": 123, "fields": {"System.Title": "Story", "System.WorkItemType": "User Story",
                                   "System.State": "Active", "System.AreaPath": "A",
                                   "System.IterationPath": "I"}},
        ]})

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        ret = main(["register", "--profile", "test",
                     "--area", "A", "--iteration", "I", "--ids", "123"])

    assert ret == 0
    output = capsys.readouterr().out
    assert "Registered" in output


def test_register_invalid_ids(capsys, monkeypatch, tmp_path):
    _patch_profile(monkeypatch)
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    ret = main(["register", "--profile", "test",
                 "--area", "A", "--iteration", "I", "--ids", "abc"])
    assert ret == 1


def test_register_warns_unknown_ids(capsys, monkeypatch, tmp_path):
    """E1: Warn on IDs ADO returns no data for."""
    _patch_profile(monkeypatch)
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))

    def fake_ado_request(url, method="GET", **kwargs):
        # Return only ID 123, not 999
        return _mock_response(200, {"value": [
            {"id": 123, "fields": {"System.Title": "Story", "System.WorkItemType": "User Story",
                                   "System.State": "Active", "System.AreaPath": "A",
                                   "System.IterationPath": "I"}},
        ]})

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        ret = main(["register", "--profile", "test",
                     "--area", "A", "--iteration", "I", "--ids", "123,999"])

    assert ret == 0
    output = capsys.readouterr().out
    assert "999" in output
    assert "WARNING" in output


def test_register_with_parent_epic_stores_epic_id(capsys, monkeypatch, tmp_path):
    _patch_profile(monkeypatch)
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))

    def fake_ado_request(url, method="GET", payload=None, **kwargs):
        if method == "POST":
            return _mock_response(200, {"workItems": [{"id": 101}]})
        return _mock_response(200, {"value": [
            {"id": 101, "fields": {"System.Title": "Story", "System.WorkItemType": "User Story",
                                   "System.State": "Active", "System.AreaPath": "A",
                                   "System.IterationPath": "I"}},
        ]})

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        ret = main(["register", "--profile", "test",
                     "--area", "A", "--iteration", "I", "--parent-epic", "500"])

    assert ret == 0
    # Verify registry has the epic ID
    from story_context.registry import load_registry
    reg = load_registry("test")
    assert 101 in reg.entries
    assert reg.entries[101].parent_epic_id == 500


def test_register_ids_and_epic_mutually_exclusive(capsys, monkeypatch, tmp_path):
    _patch_profile(monkeypatch)
    # argparse exits with code 2 when mutually exclusive args are both given
    with pytest.raises(SystemExit) as exc_info:
        main(["register", "--profile", "test",
              "--area", "A", "--iteration", "I",
              "--ids", "123", "--parent-epic", "500"])
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------

def test_refresh_no_ids_refreshes_all(capsys, monkeypatch, tmp_path):
    _patch_profile(monkeypatch)
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    _write_registry(str(tmp_path), "test", {
        "123": {"id": 123, "title": "Story", "type": "User Story", "area_path": "A",
                "iteration_path": "I", "state": "Active", "parent_epic_id": None,
                "registered_at": "2026-04-06T14:00:00Z", "last_refreshed_at": None,
                "corpus_exists": False},
    })

    def fake_ado_request(url, method="GET", **kwargs):
        if "$expand=relations" in url:
            return _mock_response(200, {
                "id": 123,
                "fields": {"System.Title": "Story", "System.State": "Active"},
                "relations": [],
            })
        return _mock_response(200, {"value": []})

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        ret = main(["refresh", "--profile", "test"])

    assert ret == 0
    output = capsys.readouterr().out
    assert "Refreshed 1 stories" in output


def test_refresh_ids_subset(capsys, monkeypatch, tmp_path):
    _patch_profile(monkeypatch)
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    _write_registry(str(tmp_path), "test", {
        "123": {"id": 123, "title": "S1", "type": "User Story", "area_path": "A",
                "iteration_path": "I", "state": "Active", "parent_epic_id": None,
                "registered_at": "2026-04-06T14:00:00Z", "last_refreshed_at": None,
                "corpus_exists": False},
        "456": {"id": 456, "title": "S2", "type": "User Story", "area_path": "A",
                "iteration_path": "I", "state": "Active", "parent_epic_id": None,
                "registered_at": "2026-04-06T14:00:00Z", "last_refreshed_at": None,
                "corpus_exists": False},
    })

    call_count = {"relations": 0}

    def fake_ado_request(url, method="GET", **kwargs):
        if "$expand=relations" in url:
            call_count["relations"] += 1
            return _mock_response(200, {
                "id": 123, "fields": {"System.Title": "S1", "System.State": "Active"},
                "relations": [],
            })
        return _mock_response(200, {"value": []})

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        ret = main(["refresh", "--profile", "test", "--ids", "123"])

    assert ret == 0
    assert call_count["relations"] == 1  # Only 123 refreshed, not 456


def test_refresh_partial_failure(capsys, monkeypatch, tmp_path):
    """J1: One story fails, others succeed, exit code 1."""
    _patch_profile(monkeypatch)
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    _write_registry(str(tmp_path), "test", {
        "100": {"id": 100, "title": "Good", "type": "User Story", "area_path": "A",
                "iteration_path": "I", "state": "Active", "parent_epic_id": None,
                "registered_at": "2026-04-06T14:00:00Z", "last_refreshed_at": None,
                "corpus_exists": False},
        "200": {"id": 200, "title": "Bad", "type": "User Story", "area_path": "A",
                "iteration_path": "I", "state": "Active", "parent_epic_id": None,
                "registered_at": "2026-04-06T14:00:00Z", "last_refreshed_at": None,
                "corpus_exists": False},
    })

    def fake_ado_request(url, method="GET", **kwargs):
        if "$expand=relations" in url and "200" in url:
            return _mock_response(404, {"message": "Not found"})
        if "$expand=relations" in url:
            return _mock_response(200, {
                "id": 100, "fields": {"System.Title": "Good", "System.State": "Active"},
                "relations": [],
            })
        return _mock_response(200, {"value": []})

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        ret = main(["refresh", "--profile", "test"])

    assert ret == 1
    output = capsys.readouterr().out
    assert "OK #100" in output
    assert "FAILED #200" in output

    # Story 100 corpus should exist, 200 should not
    assert os.path.exists(os.path.join(str(tmp_path), "corpus", "test", "100", "story.md"))
    assert not os.path.exists(os.path.join(str(tmp_path), "corpus", "test", "200", "story.md"))


# ---------------------------------------------------------------------------
# build-context
# ---------------------------------------------------------------------------

def test_build_context_with_epic_flag(capsys, monkeypatch, tmp_path):
    _patch_profile(monkeypatch)
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    _write_registry(str(tmp_path), "test", {
        "101": {"id": 101, "title": "S1", "type": "User Story", "area_path": "A",
                "iteration_path": "I", "state": "Active", "parent_epic_id": 500,
                "registered_at": "2026-04-06T14:00:00Z", "last_refreshed_at": "2026-04-06T15:00:00Z",
                "corpus_exists": True},
    })
    _write_corpus(str(tmp_path), "test", 101)

    output_path = str(tmp_path / "out.md")
    ret = main(["build-context", "--profile", "test",
                 "--epic", "500", "--output", output_path])

    assert ret == 0
    assert os.path.exists(output_path)


def test_build_context_epic_no_matching_stories_raises(capsys, monkeypatch, tmp_path):
    _patch_profile(monkeypatch)
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    _write_registry(str(tmp_path), "test", {
        "101": {"id": 101, "title": "S1", "type": "User Story", "area_path": "A",
                "iteration_path": "I", "state": "Active", "parent_epic_id": 500,
                "registered_at": "2026-04-06T14:00:00Z", "last_refreshed_at": None,
                "corpus_exists": False},
    })

    output_path = str(tmp_path / "out.md")
    ret = main(["build-context", "--profile", "test",
                 "--epic", "999", "--output", output_path])

    assert ret == 1  # StoryContextError → exit code 1


def test_build_context_missing_output_arg(capsys, monkeypatch, tmp_path):
    _patch_profile(monkeypatch)
    # Missing --output should cause argparse error
    with pytest.raises(SystemExit) as exc_info:
        main(["build-context", "--profile", "test", "--ids", "123"])
    assert exc_info.value.code != 0
