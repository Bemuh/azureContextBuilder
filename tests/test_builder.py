"""Tests for story_context/builder.py"""
import json
import os
import pytest

from story_context.builder import build_context_bundle, build_manifest, load_story_files
import story_context.config as cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_corpus(data_root: str, profile: str, story_id: int,
                  title: str = "Test Story", state: str = "Active") -> None:
    story_dir = os.path.join(data_root, "corpus", profile, str(story_id))
    os.makedirs(story_dir, exist_ok=True)

    story_md = (
        f"<!-- story_context metadata\nid: {story_id}\n-->\n\n"
        f"# [{story_id}] {title}\n\n## Description\n\nSome content.\n"
    )
    with open(os.path.join(story_dir, "story.md"), "w") as fh:
        fh.write(story_md)

    meta = {"story_id": story_id, "fetched_at": "2026-04-06T15:00:00Z", "conversions": []}
    with open(os.path.join(story_dir, "refresh_meta.json"), "w") as fh:
        json.dump(meta, fh)


def _write_digest(data_root: str, profile: str, content: str = "# Digest") -> None:
    digest_dir = os.path.join(data_root, "project_digest")
    os.makedirs(digest_dir, exist_ok=True)
    with open(os.path.join(digest_dir, f"{profile}.md"), "w") as fh:
        fh.write(content)


# ---------------------------------------------------------------------------
# load_story_files
# ---------------------------------------------------------------------------

def test_load_story_files_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    result = load_story_files("myprofile", 999)
    assert result is None


def test_load_story_files_returns_content(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    _write_corpus(str(tmp_path), "myprofile", 123)
    result = load_story_files("myprofile", 123)
    assert result is not None
    assert "story_md" in result
    assert "meta" in result
    assert "123" in result["story_md"]


# ---------------------------------------------------------------------------
# build_manifest
# ---------------------------------------------------------------------------

def test_manifest_structure():
    m = build_manifest("myprofile", [123, 456, 789], [123, 456], [789], "2026-04-06T15:00:00Z")
    assert m["profile"] == "myprofile"
    assert m["generated_at"] == "2026-04-06T15:00:00Z"
    assert m["requested"] == [123, 456, 789]
    assert m["included"] == [123, 456]
    assert m["missing"] == [789]


# ---------------------------------------------------------------------------
# build_context_bundle
# ---------------------------------------------------------------------------

def test_build_context_bundle_all_present(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    _write_corpus(str(tmp_path), "myprofile", 123)
    _write_corpus(str(tmp_path), "myprofile", 456)
    _write_digest(str(tmp_path), "myprofile")

    output = str(tmp_path / "out.md")
    manifest = build_context_bundle("myprofile", [123, 456], output)

    assert manifest["included"] == [123, 456]
    assert manifest["missing"] == []
    assert os.path.exists(output)


def test_build_context_bundle_missing_story(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    _write_corpus(str(tmp_path), "myprofile", 123)
    _write_digest(str(tmp_path), "myprofile")

    output = str(tmp_path / "out.md")
    manifest = build_context_bundle("myprofile", [123, 999], output)

    assert 123 in manifest["included"]
    assert 999 in manifest["missing"]

    content = open(output).read()
    assert "999" in content  # missing ID mentioned


def test_build_context_bundle_deterministic_order(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    _write_corpus(str(tmp_path), "myprofile", 300, title="Third")
    _write_corpus(str(tmp_path), "myprofile", 100, title="First")
    _write_corpus(str(tmp_path), "myprofile", 200, title="Second")
    _write_digest(str(tmp_path), "myprofile")

    output = str(tmp_path / "out.md")
    # Pass IDs in reverse order
    build_context_bundle("myprofile", [300, 100, 200], output)

    content = open(output).read()
    pos_100 = content.find("Story #100")
    pos_200 = content.find("Story #200")
    pos_300 = content.find("Story #300")

    assert pos_100 < pos_200 < pos_300


def test_build_context_no_digest(tmp_path, monkeypatch):
    """K1: Warning placeholder included when digest absent."""
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    _write_corpus(str(tmp_path), "myprofile", 123)
    # No digest file written

    output = str(tmp_path / "out.md")
    manifest = build_context_bundle("myprofile", [123], output)

    content = open(output).read()
    assert "digest not available" in content.lower() or "not available" in content
    assert 123 in manifest["included"]


def test_output_file_written(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    _write_corpus(str(tmp_path), "myprofile", 123)

    output = str(tmp_path / "subdir" / "bundle.md")
    build_context_bundle("myprofile", [123], output)
    assert os.path.exists(output)


def test_build_context_manifest_json_in_output(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))
    _write_corpus(str(tmp_path), "myprofile", 123)

    output = str(tmp_path / "out.md")
    build_context_bundle("myprofile", [123], output)

    content = open(output).read()
    # Find JSON block
    assert "```json" in content
    json_start = content.index("```json") + 7
    json_end = content.index("```", json_start)
    manifest_json = json.loads(content[json_start:json_end].strip())
    assert manifest_json["profile"] == "myprofile"
    assert 123 in manifest_json["included"]
