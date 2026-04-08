"""ADO query logic for story_context.

Pure data-fetching layer — no rendering, no disk writes.
"""
from __future__ import annotations

from . import ado

# Fields fetched for every registered story
_CORE_STORY_FIELDS = [
    "System.Id",
    "System.Title",
    "System.WorkItemType",
    "System.State",
    "System.AreaPath",
    "System.IterationPath",
    "System.Tags",
    "System.Parent",           # needed for epic grouping
    "System.CreatedBy",
    "System.CreatedDate",
    "System.ChangedBy",
    "System.ChangedDate",
    "System.Description",
    "Microsoft.VSTS.Common.AcceptanceCriteria",
]

# Best-effort fields that may not exist in every ADO project.
# If ADO rejects the request, we retry without these.
_OPTIONAL_STORY_FIELDS = [
    "Custom.AcceptanceCriteria",
]

STORY_FIELDS = _CORE_STORY_FIELDS + _OPTIONAL_STORY_FIELDS

# Fields fetched for direct child tasks
CHILD_FIELDS = [
    "System.Id",
    "System.Title",
    "System.State",
    "System.WorkItemType",
]

# Work item types shown by list-stories
LIST_TYPES = [
    "User Story",
    "Product Backlog Item",
    "Requirement",
    "Feature",
    "Epic",
]

# ADO relation type for parent → child
_REL_CHILD = "System.LinkTypes.Hierarchy-Forward"
# ADO relation type for child → parent
_REL_PARENT = "System.LinkTypes.Hierarchy-Reverse"


# ---------------------------------------------------------------------------
# list-stories
# ---------------------------------------------------------------------------

def list_stories(
    org: str,
    project: str,
    area_path: str,
    iteration_path: str,
    chunk_size: int = 200,
    debug: int = 0,
    parent_epic_id: int | None = None,
) -> list[dict]:
    """Return parent story items matching area, iteration, and optional epic.

    Each returned dict has an "id" key and a "fields" dict with STORY_FIELDS.
    """
    types_clause = ", ".join(f"'{t}'" for t in LIST_TYPES)
    wiql = (
        f"SELECT [System.Id] FROM WorkItems "
        f"WHERE [System.AreaPath] UNDER '{area_path}' "
        f"AND [System.IterationPath] UNDER '{iteration_path}' "
        f"AND [System.WorkItemType] IN ({types_clause})"
    )
    if parent_epic_id is not None:
        wiql += f" AND [System.Parent] = {parent_epic_id}"
    wiql += " ORDER BY [System.Id]"

    result = ado.wiql_query(org, project, wiql, debug=debug)
    ids = [item["id"] for item in result.get("workItems", [])]
    if not ids:
        return []

    return fetch_stories_by_ids(org, ids, chunk_size=chunk_size, debug=debug)


# ---------------------------------------------------------------------------
# fetch by IDs
# ---------------------------------------------------------------------------

def fetch_stories_by_ids(
    org: str,
    ids: list[int],
    chunk_size: int = 200,
    debug: int = 0,
) -> list[dict]:
    """Fetch STORY_FIELDS for the given IDs.

    Falls back to core fields only if ADO rejects an optional field
    (e.g. Custom.AcceptanceCriteria does not exist in this project).
    """
    try:
        return ado.fetch_work_items_chunked(org, ids, STORY_FIELDS, chunk_size, debug=debug)
    except ado.AdoError as exc:
        msg = str(exc)
        if "Cannot find field" in msg and any(f in msg for f in _OPTIONAL_STORY_FIELDS):
            if debug:
                print(f"Retrying without optional fields: {_OPTIONAL_STORY_FIELDS}")
            return ado.fetch_work_items_chunked(
                org, ids, _CORE_STORY_FIELDS, chunk_size, debug=debug,
            )
        raise


# ---------------------------------------------------------------------------
# Relation extraction
# ---------------------------------------------------------------------------

def _extract_id_from_url(url: str) -> int | None:
    """Extract work item ID from an ADO relation URL like .../workitems/123"""
    try:
        return int(url.rstrip("/").rsplit("/", 1)[-1])
    except (ValueError, AttributeError):
        return None


def extract_parent_link(item: dict) -> int | None:
    """Return the parent work item ID from a $expand=relations item, or None."""
    for rel in item.get("relations") or []:
        if rel.get("rel") == _REL_PARENT:
            return _extract_id_from_url(rel.get("url", ""))
    return None


def extract_child_task_ids(item: dict) -> list[int]:
    """Return list of direct child work item IDs (all types)."""
    ids: list[int] = []
    for rel in item.get("relations") or []:
        if rel.get("rel") == _REL_CHILD:
            wid = _extract_id_from_url(rel.get("url", ""))
            if wid is not None:
                ids.append(wid)
    return ids


# ---------------------------------------------------------------------------
# Child task fetch
# ---------------------------------------------------------------------------

def fetch_child_tasks(
    org: str,
    child_ids: list[int],
    chunk_size: int = 200,
    debug: int = 0,
) -> list[dict]:
    """Fetch CHILD_FIELDS for child IDs, filtered to WorkItemType == 'Task'."""
    if not child_ids:
        return []
    items = ado.fetch_work_items_chunked(org, child_ids, CHILD_FIELDS, chunk_size, debug=debug)
    tasks = []
    for item in items:
        f = item.get("fields", {})
        if f.get("System.WorkItemType") == "Task":
            tasks.append({
                "id": item.get("id"),
                "title": f.get("System.Title", ""),
                "state": f.get("System.State", ""),
                "type": f.get("System.WorkItemType", "Task"),
            })
    return tasks


# ---------------------------------------------------------------------------
# Full story snapshot
# ---------------------------------------------------------------------------

def build_story_snapshot(
    org: str,
    story_id: int,
    chunk_size: int = 200,
    debug: int = 0,
) -> dict:
    """Fetch a complete story snapshot for corpus writing.

    Returns:
        {
            "fields": {field_ref: value, ...},
            "parent_id": int | None,
            "child_tasks": [{"id", "title", "state", "type"}, ...]
        }
    """
    item = ado.fetch_work_item_with_relations(org, story_id, debug=debug)

    # Fields are nested under "fields" in the response
    fields = item.get("fields", {})

    parent_id = extract_parent_link(item)
    child_ids = extract_child_task_ids(item)
    child_tasks = fetch_child_tasks(org, child_ids, chunk_size=chunk_size, debug=debug)

    return {
        "fields": fields,
        "parent_id": parent_id,
        "child_tasks": child_tasks,
    }
