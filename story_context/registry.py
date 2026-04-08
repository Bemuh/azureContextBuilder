"""Registry CRUD for story_context.

Stores the set of explicitly registered story IDs per profile in
story_context_data/registries/<profile>.yml.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .config import StoryContextError, load_yaml, registry_path, save_yaml
from .utils import now_iso


@dataclass
class RegistryEntry:
    id: int
    title: str
    type: str
    area_path: str
    iteration_path: str
    state: str
    parent_epic_id: int | None
    registered_at: str
    last_refreshed_at: str | None
    corpus_exists: bool

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "type": self.type,
            "area_path": self.area_path,
            "iteration_path": self.iteration_path,
            "state": self.state,
            "parent_epic_id": self.parent_epic_id,
            "registered_at": self.registered_at,
            "last_refreshed_at": self.last_refreshed_at,
            "corpus_exists": self.corpus_exists,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RegistryEntry":
        return cls(
            id=int(d["id"]),
            title=d.get("title", ""),
            type=d.get("type", ""),
            area_path=d.get("area_path", ""),
            iteration_path=d.get("iteration_path", ""),
            state=d.get("state", ""),
            parent_epic_id=d.get("parent_epic_id"),
            registered_at=d.get("registered_at", ""),
            last_refreshed_at=d.get("last_refreshed_at"),
            corpus_exists=bool(d.get("corpus_exists", False)),
        )


@dataclass
class Registry:
    profile: str
    created_at: str
    updated_at: str
    entries: dict[int, RegistryEntry] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "entries": {
                str(k): v.to_dict() for k, v in sorted(self.entries.items())
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Registry":
        entries: dict[int, RegistryEntry] = {}
        for k, v in (d.get("entries") or {}).items():
            entry = RegistryEntry.from_dict(v)
            entries[entry.id] = entry
        return cls(
            profile=d.get("profile", ""),
            created_at=d.get("created_at", now_iso()),
            updated_at=d.get("updated_at", now_iso()),
            entries=entries,
        )

    @classmethod
    def empty(cls, profile_name: str) -> "Registry":
        ts = now_iso()
        return cls(profile=profile_name, created_at=ts, updated_at=ts, entries={})


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------

def load_registry(profile_name: str) -> Registry:
    path = registry_path(profile_name)
    data = load_yaml(path)
    if not data:
        return Registry.empty(profile_name)
    return Registry.from_dict(data)


def save_registry(registry: Registry, profile_name: str) -> None:
    registry.updated_at = now_iso()
    path = registry_path(profile_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_yaml(path, registry.to_dict())


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------

def _entry_from_ado_fields(fields: dict, parent_epic_id: int | None) -> RegistryEntry:
    return RegistryEntry(
        id=int(fields.get("id") or fields.get("System.Id", 0)),
        title=fields.get("fields", {}).get("System.Title") or fields.get("System.Title", ""),
        type=fields.get("fields", {}).get("System.WorkItemType") or fields.get("System.WorkItemType", ""),
        area_path=fields.get("fields", {}).get("System.AreaPath") or fields.get("System.AreaPath", ""),
        iteration_path=fields.get("fields", {}).get("System.IterationPath") or fields.get("System.IterationPath", ""),
        state=fields.get("fields", {}).get("System.State") or fields.get("System.State", ""),
        parent_epic_id=parent_epic_id,
        registered_at=now_iso(),
        last_refreshed_at=None,
        corpus_exists=False,
    )


def add_entries(
    registry: Registry,
    items: list[dict],
    parent_epic_id: int | None = None,
) -> tuple[list[int], list[int]]:
    """Add or update registry entries from ADO work item dicts.

    Returns (new_ids, existing_ids).
    New entries get parent_epic_id set. Existing entries have their mutable
    fields (title, state, area_path, iteration_path) updated but registered_at
    and parent_epic_id are preserved.
    """
    new_ids: list[int] = []
    existing_ids: list[int] = []

    for item in items:
        story_id = int(item.get("id") or item.get("System.Id", 0))
        if story_id == 0:
            continue

        # Normalise: ADO batch responses nest fields under "fields" key
        f = item.get("fields") or item

        if story_id in registry.entries:
            # Update mutable fields, preserve registered_at and parent_epic_id
            entry = registry.entries[story_id]
            entry.title = f.get("System.Title", entry.title)
            entry.state = f.get("System.State", entry.state)
            entry.area_path = f.get("System.AreaPath", entry.area_path)
            entry.iteration_path = f.get("System.IterationPath", entry.iteration_path)
            entry.type = f.get("System.WorkItemType", entry.type)
            existing_ids.append(story_id)
        else:
            # Flatten for _entry_from_ado_fields
            flat = {"id": story_id, **f}
            entry = _entry_from_ado_fields(flat, parent_epic_id)
            registry.entries[story_id] = entry
            new_ids.append(story_id)

    return new_ids, existing_ids


def mark_refreshed(registry: Registry, story_id: int, timestamp: str) -> None:
    if story_id in registry.entries:
        registry.entries[story_id].last_refreshed_at = timestamp
        registry.entries[story_id].corpus_exists = True


def get_registered_ids(registry: Registry) -> list[int]:
    return sorted(registry.entries.keys())


def filter_ids(registry: Registry, ids: list[int] | None) -> list[int]:
    """Return requested IDs after validating they are all registered.

    If ids is None, returns all registered IDs.
    Raises StoryContextError for any IDs not in the registry.
    """
    if ids is None:
        return get_registered_ids(registry)

    unknown = [i for i in ids if i not in registry.entries]
    if unknown:
        raise StoryContextError(
            f"IDs not found in registry: {', '.join(str(i) for i in unknown)}. "
            "Register them first with 'story_context register'."
        )
    return sorted(set(ids))


def filter_ids_by_epic(registry: Registry, epic_id: int) -> list[int]:
    """Return all registered story IDs whose parent_epic_id matches epic_id.

    Raises StoryContextError if no stories are registered for that epic.
    """
    matching = sorted(
        story_id
        for story_id, entry in registry.entries.items()
        if entry.parent_epic_id == epic_id
    )
    if not matching:
        raise StoryContextError(
            f"No stories registered for epic {epic_id}. "
            "Use 'story_context register --parent-epic {epic_id}' to register stories."
        )
    return matching
