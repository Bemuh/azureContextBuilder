"""Tests for story_context/registry.py"""
import os
import pytest

from story_context.registry import (
    Registry,
    RegistryEntry,
    add_entries,
    filter_ids,
    filter_ids_by_epic,
    get_registered_ids,
    load_registry,
    mark_refreshed,
    save_registry,
)
from story_context.config import StoryContextError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ado_item(story_id: int, title: str = "Story", state: str = "Active",
              wi_type: str = "User Story", area: str = "Proj\\Area",
              iteration: str = "Proj\\Sprint 01") -> dict:
    """Simulate ADO batch response item (fields nested under 'fields')."""
    return {
        "id": story_id,
        "fields": {
            "System.Title": title,
            "System.State": state,
            "System.WorkItemType": wi_type,
            "System.AreaPath": area,
            "System.IterationPath": iteration,
        },
    }


# ---------------------------------------------------------------------------
# load_registry
# ---------------------------------------------------------------------------

def test_load_empty_registry_when_file_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("story_context.config.DATA_ROOT", str(tmp_path))
    reg = load_registry("myprofile")
    assert reg.profile == "myprofile"
    assert reg.entries == {}


# ---------------------------------------------------------------------------
# add_entries
# ---------------------------------------------------------------------------

def test_add_entries_new(tmp_path, monkeypatch):
    monkeypatch.setattr("story_context.config.DATA_ROOT", str(tmp_path))
    reg = Registry.empty("myprofile")
    items = [_ado_item(123), _ado_item(456)]
    new_ids, existing_ids = add_entries(reg, items)
    assert sorted(new_ids) == [123, 456]
    assert existing_ids == []
    assert 123 in reg.entries
    assert 456 in reg.entries
    assert reg.entries[123].title == "Story"
    assert reg.entries[123].corpus_exists is False
    assert reg.entries[123].last_refreshed_at is None


def test_add_entries_idempotent_preserves_registered_at(tmp_path, monkeypatch):
    monkeypatch.setattr("story_context.config.DATA_ROOT", str(tmp_path))
    reg = Registry.empty("myprofile")
    items = [_ado_item(123, title="Original")]
    add_entries(reg, items)
    original_registered_at = reg.entries[123].registered_at

    updated = [_ado_item(123, title="Updated", state="Closed")]
    new_ids, existing_ids = add_entries(reg, updated)

    assert new_ids == []
    assert existing_ids == [123]
    assert reg.entries[123].title == "Updated"
    assert reg.entries[123].state == "Closed"
    assert reg.entries[123].registered_at == original_registered_at


def test_add_entries_returns_correct_counts():
    reg = Registry.empty("myprofile")
    add_entries(reg, [_ado_item(100), _ado_item(200)])
    new_ids, existing_ids = add_entries(reg, [_ado_item(200), _ado_item(300)])
    assert sorted(new_ids) == [300]
    assert existing_ids == [200]


def test_add_entries_stores_parent_epic_id():
    reg = Registry.empty("myprofile")
    add_entries(reg, [_ado_item(123)], parent_epic_id=500)
    assert reg.entries[123].parent_epic_id == 500


def test_add_entries_parent_epic_id_none_by_default():
    reg = Registry.empty("myprofile")
    add_entries(reg, [_ado_item(123)])
    assert reg.entries[123].parent_epic_id is None


def test_add_entries_existing_preserves_parent_epic_id():
    """Re-registering an existing entry should NOT overwrite parent_epic_id."""
    reg = Registry.empty("myprofile")
    add_entries(reg, [_ado_item(123)], parent_epic_id=500)
    add_entries(reg, [_ado_item(123)], parent_epic_id=999)
    assert reg.entries[123].parent_epic_id == 500


# ---------------------------------------------------------------------------
# mark_refreshed
# ---------------------------------------------------------------------------

def test_mark_refreshed():
    reg = Registry.empty("myprofile")
    add_entries(reg, [_ado_item(123)])
    mark_refreshed(reg, 123, "2026-04-06T15:00:00Z")
    assert reg.entries[123].last_refreshed_at == "2026-04-06T15:00:00Z"
    assert reg.entries[123].corpus_exists is True


def test_mark_refreshed_unknown_id_is_noop():
    reg = Registry.empty("myprofile")
    mark_refreshed(reg, 999, "2026-04-06T15:00:00Z")  # should not raise


# ---------------------------------------------------------------------------
# filter_ids
# ---------------------------------------------------------------------------

def test_filter_ids_none_returns_all():
    reg = Registry.empty("myprofile")
    add_entries(reg, [_ado_item(100), _ado_item(200), _ado_item(300)])
    assert filter_ids(reg, None) == [100, 200, 300]


def test_filter_ids_subset_returns_sorted():
    reg = Registry.empty("myprofile")
    add_entries(reg, [_ado_item(100), _ado_item(200), _ado_item(300)])
    assert filter_ids(reg, [300, 100]) == [100, 300]


def test_filter_ids_unknown_raises():
    reg = Registry.empty("myprofile")
    add_entries(reg, [_ado_item(100)])
    with pytest.raises(StoryContextError, match="999"):
        filter_ids(reg, [100, 999])


# ---------------------------------------------------------------------------
# filter_ids_by_epic
# ---------------------------------------------------------------------------

def test_filter_ids_by_epic_returns_matching():
    reg = Registry.empty("myprofile")
    add_entries(reg, [_ado_item(10), _ado_item(20)], parent_epic_id=500)
    add_entries(reg, [_ado_item(30)], parent_epic_id=600)
    result = filter_ids_by_epic(reg, 500)
    assert result == [10, 20]


def test_filter_ids_by_epic_unknown_raises():
    reg = Registry.empty("myprofile")
    add_entries(reg, [_ado_item(10)], parent_epic_id=500)
    with pytest.raises(StoryContextError, match="999"):
        filter_ids_by_epic(reg, 999)


def test_filter_ids_by_epic_no_epic_entries_raises():
    reg = Registry.empty("myprofile")
    add_entries(reg, [_ado_item(10)])  # no parent_epic_id
    with pytest.raises(StoryContextError, match="500"):
        filter_ids_by_epic(reg, 500)


# ---------------------------------------------------------------------------
# save / load roundtrip
# ---------------------------------------------------------------------------

def test_save_and_reload_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("story_context.config.DATA_ROOT", str(tmp_path))
    import story_context.registry as reg_mod
    monkeypatch.setattr(reg_mod, "registry_path",
                        lambda name: str(tmp_path / f"{name}.yml"))

    reg = Registry.empty("myprofile")
    add_entries(reg, [_ado_item(123, title="Hello")], parent_epic_id=500)
    mark_refreshed(reg, 123, "2026-04-06T16:00:00Z")
    save_registry(reg, "myprofile")

    loaded = load_registry("myprofile")
    assert loaded.profile == "myprofile"
    assert 123 in loaded.entries
    assert loaded.entries[123].title == "Hello"
    assert loaded.entries[123].parent_epic_id == 500
    assert loaded.entries[123].corpus_exists is True
    assert loaded.entries[123].last_refreshed_at == "2026-04-06T16:00:00Z"


def test_entries_keyed_as_strings_in_yaml(tmp_path, monkeypatch):
    """YAML serialization uses string keys for entries."""
    import yaml
    import story_context.registry as reg_mod
    monkeypatch.setattr(reg_mod, "registry_path",
                        lambda name: str(tmp_path / f"{name}.yml"))

    reg = Registry.empty("myprofile")
    add_entries(reg, [_ado_item(123)])
    save_registry(reg, "myprofile")

    with open(tmp_path / "myprofile.yml", "r") as fh:
        raw = yaml.safe_load(fh)

    assert "123" in raw["entries"]
    assert 123 not in raw["entries"]


# ---------------------------------------------------------------------------
# get_registered_ids
# ---------------------------------------------------------------------------

def test_get_registered_ids_sorted():
    reg = Registry.empty("myprofile")
    add_entries(reg, [_ado_item(300), _ado_item(100), _ado_item(200)])
    assert get_registered_ids(reg) == [100, 200, 300]
