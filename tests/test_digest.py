"""Tests for story_context/digest.py"""
import os
import pytest

from story_context.digest import (
    _is_safe_path,
    find_digest_sources,
    generate_digest,
    save_digest,
    DIGEST_SOURCE_FILES,
)


# ---------------------------------------------------------------------------
# _is_safe_path
# ---------------------------------------------------------------------------

def test_is_safe_path_rejects_keys_dir(tmp_path):
    assert _is_safe_path(str(tmp_path / "keys" / "something.txt")) is False


def test_is_safe_path_rejects_pattoken_enc(tmp_path):
    assert _is_safe_path(str(tmp_path / "patToken.enc")) is False


def test_is_safe_path_rejects_encryption_key(tmp_path):
    assert _is_safe_path(str(tmp_path / "encryption.key")) is False


def test_is_safe_path_allows_normal_files(tmp_path):
    assert _is_safe_path(str(tmp_path / "README.MD")) is True
    assert _is_safe_path(str(tmp_path / "PLAN.md")) is True


# ---------------------------------------------------------------------------
# find_digest_sources
# ---------------------------------------------------------------------------

def _create_files(directory: str, names: list[str]) -> None:
    for name in names:
        path = os.path.join(directory, name)
        with open(path, "w") as fh:
            fh.write(f"Content of {name}")


def test_find_digest_sources_all_present(tmp_path):
    _create_files(str(tmp_path), ["README.MD", "PLAN.md", "AGENTS.md"])
    sources = find_digest_sources(str(tmp_path))
    names = [n for n, _ in sources]
    assert "README.MD" in names
    assert "PLAN.md" in names
    assert "AGENTS.md" in names
    assert len(sources) == 3


def test_find_digest_sources_partial(tmp_path):
    _create_files(str(tmp_path), ["README.MD"])
    sources = find_digest_sources(str(tmp_path))
    names = [n for n, _ in sources]
    assert "README.MD" in names
    assert "PLAN.md" not in names
    assert len(sources) == 1


def test_find_digest_sources_excludes_keys_dir(tmp_path):
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir()
    (keys_dir / "README.MD").write_text("Should not be included")
    _create_files(str(tmp_path), ["README.MD"])
    sources = find_digest_sources(str(tmp_path))
    # Should find README.MD at top level, not inside keys/
    assert all(os.path.dirname(p) == str(tmp_path) for _, p in sources)


def test_find_digest_sources_case_insensitive(tmp_path):
    """readme.md (lowercase) should match README.MD pattern."""
    (tmp_path / "readme.md").write_text("Lowercase readme")
    sources = find_digest_sources(str(tmp_path))
    names = [n for n, _ in sources]
    # Should find one entry matching readme.md
    assert len(sources) == 1


def test_find_digest_sources_order_matches_priority(tmp_path):
    _create_files(str(tmp_path), ["AGENTS.md", "README.MD", "PLAN.md"])
    sources = find_digest_sources(str(tmp_path))
    names = [n.lower() for n, _ in sources]
    # readme should come before plan, plan before agents
    assert names.index("readme.md") < names.index("plan.md")
    assert names.index("plan.md") < names.index("agents.md")


# ---------------------------------------------------------------------------
# generate_digest
# ---------------------------------------------------------------------------

def test_generate_digest_structure(tmp_path):
    _create_files(str(tmp_path), ["README.MD", "PLAN.md"])
    content = generate_digest("myprofile", str(tmp_path))
    assert "<!-- project_digest" in content
    assert "profile: myprofile" in content
    assert "# Project Digest" in content
    assert "## README.MD" in content
    assert "## PLAN.md" in content


def test_generate_digest_missing_file_note(tmp_path):
    _create_files(str(tmp_path), ["README.MD"])
    content = generate_digest("myprofile", str(tmp_path))
    assert "PLAN.md not found at project root" in content
    assert "AGENTS.md not found at project root" in content


def test_generate_digest_includes_file_content(tmp_path):
    readme_path = tmp_path / "README.MD"
    readme_path.write_text("# My Project\nThis is the readme.")
    content = generate_digest("myprofile", str(tmp_path))
    assert "# My Project" in content
    assert "This is the readme." in content


def test_generate_digest_warns_over_50kb(tmp_path, capsys):
    # Create a large README
    readme_path = tmp_path / "README.MD"
    readme_path.write_text("x" * 60_000)
    generate_digest("myprofile", str(tmp_path))
    captured = capsys.readouterr()
    assert "Warning" in captured.out or "Warning" in captured.err


def test_generate_digest_no_warning_under_50kb(tmp_path, capsys):
    _create_files(str(tmp_path), ["README.MD"])
    generate_digest("myprofile", str(tmp_path))
    captured = capsys.readouterr()
    assert "Warning" not in captured.out
    assert "Warning" not in captured.err


# ---------------------------------------------------------------------------
# save_digest
# ---------------------------------------------------------------------------

def test_save_digest_writes_file(tmp_path, monkeypatch):
    import story_context.config as cfg
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path))

    content = "# My Digest"
    save_digest(content, "testprofile")

    digest_file = tmp_path / "project_digest" / "testprofile.md"
    assert digest_file.exists()
    assert digest_file.read_text() == content
