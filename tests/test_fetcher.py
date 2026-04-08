"""Tests for story_context/fetcher.py

All ADO calls are mocked at story_context.ado.ado_request (I1 decision).
"""
from __future__ import annotations
import json
import pytest
from unittest.mock import MagicMock, patch

from story_context.fetcher import (
    build_story_snapshot,
    extract_child_task_ids,
    extract_parent_link,
    fetch_child_tasks,
    fetch_stories_by_ids,
    list_stories,
)
from story_context.ado import AdoError


# ---------------------------------------------------------------------------
# Helpers to build fake ADO responses
# ---------------------------------------------------------------------------

def _mock_response(status: int, body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


def _wiql_response(ids: list[int]) -> MagicMock:
    return _mock_response(200, {"workItems": [{"id": i} for i in ids]})


def _items_response(items: list[dict]) -> MagicMock:
    return _mock_response(200, {"value": items})


def _item_with_relations(story_id: int, fields: dict, relations: list[dict]) -> dict:
    return {"id": story_id, "fields": fields, "relations": relations}


def _relation(rel_type: str, target_id: int) -> dict:
    return {
        "rel": rel_type,
        "url": f"https://dev.azure.com/myorg/_apis/wit/workitems/{target_id}",
    }


# ---------------------------------------------------------------------------
# list_stories
# ---------------------------------------------------------------------------

def test_list_stories_wiql_query(monkeypatch):
    """Correct WIQL built for area + iteration."""
    calls: list = []

    def fake_ado_request(url, method="GET", payload=None, **kwargs):
        calls.append({"url": url, "method": method, "payload": payload})
        if method == "POST":  # WIQL
            return _wiql_response([101, 102])
        # GET = fetch_work_items
        return _items_response([
            {"id": 101, "fields": {"System.Title": "Story A", "System.WorkItemType": "User Story"}},
            {"id": 102, "fields": {"System.Title": "Story B", "System.WorkItemType": "User Story"}},
        ])

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        results = list_stories("myorg", "myproject", "Proj\\Area", "Proj\\Sprint 01")

    # First call should be the WIQL POST
    wiql_call = calls[0]
    assert wiql_call["method"] == "POST"
    query = wiql_call["payload"]["query"]
    assert "UNDER 'Proj\\Area'" in query or "UNDER 'Proj\\\\Area'" in query.replace("\\\\", "\\")
    assert "User Story" in query
    assert "Product Backlog Item" in query
    assert len(results) == 2


def test_list_stories_wiql_with_parent_epic(monkeypatch):
    """--parent-epic appends AND [System.Parent] = N to WIQL."""
    captured_query: list[str] = []

    def fake_ado_request(url, method="GET", payload=None, **kwargs):
        if method == "POST":
            captured_query.append(payload["query"])
            return _wiql_response([])
        return _items_response([])

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        list_stories("myorg", "myproject", "Proj\\Area", "Proj\\Sprint 01",
                     parent_epic_id=500)

    assert len(captured_query) == 1
    assert "System.Parent" in captured_query[0]
    assert "500" in captured_query[0]


def test_list_stories_empty_result(monkeypatch):
    def fake_ado_request(url, method="GET", payload=None, **kwargs):
        if method == "POST":
            return _wiql_response([])
        return _items_response([])

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        results = list_stories("myorg", "myproject", "Area", "Iteration")

    assert results == []


# ---------------------------------------------------------------------------
# extract_parent_link
# ---------------------------------------------------------------------------

def test_extract_parent_link_present():
    item = {
        "relations": [
            _relation("System.LinkTypes.Hierarchy-Reverse", 500),
            _relation("System.LinkTypes.Hierarchy-Forward", 200),
        ]
    }
    assert extract_parent_link(item) == 500


def test_extract_parent_link_absent():
    item = {
        "relations": [
            _relation("System.LinkTypes.Hierarchy-Forward", 200),
        ]
    }
    assert extract_parent_link(item) is None


def test_extract_parent_link_no_relations():
    assert extract_parent_link({}) is None
    assert extract_parent_link({"relations": None}) is None


# ---------------------------------------------------------------------------
# extract_child_task_ids
# ---------------------------------------------------------------------------

def test_extract_child_task_ids():
    item = {
        "relations": [
            _relation("System.LinkTypes.Hierarchy-Forward", 201),
            _relation("System.LinkTypes.Hierarchy-Forward", 202),
            _relation("System.LinkTypes.Hierarchy-Reverse", 500),
        ]
    }
    ids = extract_child_task_ids(item)
    assert sorted(ids) == [201, 202]


def test_extract_child_task_ids_empty():
    assert extract_child_task_ids({"relations": []}) == []
    assert extract_child_task_ids({}) == []


# ---------------------------------------------------------------------------
# fetch_child_tasks
# ---------------------------------------------------------------------------

def test_fetch_child_tasks_filters_to_tasks(monkeypatch):
    def fake_ado_request(url, **kwargs):
        return _items_response([
            {"id": 201, "fields": {"System.Title": "Task 1", "System.State": "Done",
                                   "System.WorkItemType": "Task"}},
            {"id": 202, "fields": {"System.Title": "Bug 1", "System.State": "Active",
                                   "System.WorkItemType": "Bug"}},  # should be filtered out
        ])

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        tasks = fetch_child_tasks("myorg", [201, 202])

    assert len(tasks) == 1
    assert tasks[0]["id"] == 201
    assert tasks[0]["title"] == "Task 1"


def test_fetch_child_tasks_empty_ids():
    # Should not make any API calls
    with patch("story_context.ado.ado_request") as mock_req:
        tasks = fetch_child_tasks("myorg", [])
    mock_req.assert_not_called()
    assert tasks == []


# ---------------------------------------------------------------------------
# build_story_snapshot
# ---------------------------------------------------------------------------

def test_build_story_snapshot_structure(monkeypatch):
    """Returns dict with fields/parent_id/child_tasks keys."""
    def fake_ado_request(url, method="GET", **kwargs):
        if "$expand=relations" in url:
            return _mock_response(200, _item_with_relations(
                123,
                {"System.Title": "My Story", "System.State": "Active"},
                [
                    _relation("System.LinkTypes.Hierarchy-Reverse", 500),
                    _relation("System.LinkTypes.Hierarchy-Forward", 201),
                ],
            ))
        # Child task fetch
        return _items_response([
            {"id": 201, "fields": {"System.Title": "Task 1", "System.State": "Done",
                                   "System.WorkItemType": "Task"}},
        ])

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        snapshot = build_story_snapshot("myorg", 123)

    assert "fields" in snapshot
    assert "parent_id" in snapshot
    assert "child_tasks" in snapshot
    assert snapshot["fields"]["System.Title"] == "My Story"
    assert snapshot["parent_id"] == 500
    assert len(snapshot["child_tasks"]) == 1
    assert snapshot["child_tasks"][0]["id"] == 201


def test_build_story_snapshot_no_parent(monkeypatch):
    def fake_ado_request(url, **kwargs):
        if "$expand=relations" in url:
            return _mock_response(200, _item_with_relations(123, {}, []))
        return _items_response([])

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        snapshot = build_story_snapshot("myorg", 123)

    assert snapshot["parent_id"] is None


def test_build_story_snapshot_no_children(monkeypatch):
    def fake_ado_request(url, **kwargs):
        if "$expand=relations" in url:
            return _mock_response(200, _item_with_relations(
                123, {},
                [_relation("System.LinkTypes.Hierarchy-Reverse", 500)],
            ))
        return _items_response([])

    with patch("story_context.ado.ado_request", side_effect=fake_ado_request):
        snapshot = build_story_snapshot("myorg", 123)

    assert snapshot["child_tasks"] == []
