"""Tests for story_context/renderer.py"""
import pytest
from unittest.mock import MagicMock, patch

from story_context.renderer import (
    build_refresh_meta_json,
    build_relations_json,
    build_story_json,
    build_story_md,
    render_field_md,
)
from story_context.utils import html_to_plain_fallback


# ---------------------------------------------------------------------------
# render_field_md
# ---------------------------------------------------------------------------

def test_render_field_md_none_value():
    text, method, reason = render_field_md(None, "System.Description")
    assert text == ""
    assert method == "empty"
    assert reason is None


def test_render_field_md_empty_string():
    text, method, reason = render_field_md("   ", "System.Description")
    assert text == ""
    assert method == "empty"


def test_render_field_md_plain_text():
    text, method, reason = render_field_md("Just plain text", "System.Title")
    assert text == "Just plain text"
    assert method == "plain"
    assert reason is None


def test_render_field_md_html_import_error_fallback(monkeypatch):
    """When markitdown is not installed, fall back to stdlib strip."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "markitdown":
            raise ImportError("No module named 'markitdown'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    text, method, reason = render_field_md("<p>Hello <b>world</b></p>", "System.Description")
    assert "Hello" in text
    assert "world" in text
    assert method == "fallback"
    assert reason is None


def test_render_field_md_markitdown_success(monkeypatch):
    """Happy path: markitdown installed and works."""
    mock_result = MagicMock()
    mock_result.text_content = "**Bold text**"
    mock_md = MagicMock()
    mock_md.convert_text.return_value = mock_result
    mock_cls = MagicMock(return_value=mock_md)

    with patch.dict("sys.modules", {"markitdown": MagicMock(MarkItDown=mock_cls)}):
        text, method, reason = render_field_md("<b>Bold text</b>", "System.Description")

    assert text == "**Bold text**"
    assert method == "markitdown"
    assert reason is None


def test_render_field_md_markitdown_exception_uses_fallback(monkeypatch):
    """When markitdown raises a non-ImportError, fall back and record reason."""
    mock_md = MagicMock()
    mock_md.convert_text.side_effect = ValueError("conversion failed")
    mock_cls = MagicMock(return_value=mock_md)

    with patch.dict("sys.modules", {"markitdown": MagicMock(MarkItDown=mock_cls)}):
        text, method, reason = render_field_md("<p>Content</p>", "System.Description")

    assert "Content" in text
    assert method == "fallback"
    assert reason is not None
    assert "conversion failed" in reason
    assert len(reason) <= 200


# ---------------------------------------------------------------------------
# build_story_md structure
# ---------------------------------------------------------------------------

SAMPLE_FIELDS = {
    "System.Id": 123,
    "System.Title": "Add login flow",
    "System.WorkItemType": "User Story",
    "System.State": "Active",
    "System.AreaPath": "Project\\Area",
    "System.IterationPath": "Project\\Sprint 08",
    "System.Tags": "auth; mvp",
    "System.CreatedBy": {"displayName": "Jane Smith"},
    "System.CreatedDate": "2026-03-01T10:00:00Z",
    "System.ChangedBy": {"displayName": "John Doe"},
    "System.ChangedDate": "2026-04-01T10:00:00Z",
    "System.Description": "Login flow description",
    "Microsoft.VSTS.Common.AcceptanceCriteria": "Must handle SSO",
    "Custom.AcceptanceCriteria": None,
}

SAMPLE_TASKS = [
    {"id": 201, "title": "Implement JWT", "state": "Done"},
    {"id": 202, "title": "Write auth tests", "state": "In Progress"},
]


def test_build_story_md_contains_all_sections():
    md, log = build_story_md(123, SAMPLE_FIELDS, parent_id=456, child_tasks=SAMPLE_TASKS)
    assert "## Metadata" in md
    assert "## Acceptance Criteria" in md
    assert "## Description" in md
    assert "## Linked Tasks" in md
    assert "## Source" in md


def test_build_story_md_title_and_id():
    md, _ = build_story_md(123, SAMPLE_FIELDS, parent_id=None, child_tasks=[])
    assert "# [123] Add login flow" in md


def test_build_story_md_no_parent():
    md, _ = build_story_md(123, SAMPLE_FIELDS, parent_id=None, child_tasks=[])
    assert "Parent: #" not in md


def test_build_story_md_with_parent():
    md, _ = build_story_md(123, SAMPLE_FIELDS, parent_id=456, child_tasks=[])
    assert "Parent: #456" in md


def test_build_story_md_empty_ac_shows_placeholder():
    fields = {**SAMPLE_FIELDS, "Microsoft.VSTS.Common.AcceptanceCriteria": None}
    md, _ = build_story_md(123, fields, parent_id=None, child_tasks=[])
    assert "No acceptance criteria defined" in md


def test_build_story_md_both_ac_fields_render_separately():
    fields = {
        **SAMPLE_FIELDS,
        "Microsoft.VSTS.Common.AcceptanceCriteria": "Must handle SSO",
        "Custom.AcceptanceCriteria": "Custom criteria here",
    }
    md, _ = build_story_md(123, fields, parent_id=None, child_tasks=[])
    assert "## Acceptance Criteria" in md
    assert "## Additional Acceptance Criteria" in md
    assert "Must handle SSO" in md
    assert "Custom criteria here" in md


def test_build_story_md_custom_ac_omitted_when_empty():
    md, _ = build_story_md(123, SAMPLE_FIELDS, parent_id=None, child_tasks=[])
    assert "## Additional Acceptance Criteria" not in md


def test_build_story_md_linked_tasks_table():
    md, _ = build_story_md(123, SAMPLE_FIELDS, parent_id=None, child_tasks=SAMPLE_TASKS)
    assert "| 201 | Implement JWT | Done |" in md
    assert "| 202 | Write auth tests | In Progress |" in md


def test_build_story_md_no_linked_tasks_no_section():
    md, _ = build_story_md(123, SAMPLE_FIELDS, parent_id=None, child_tasks=[])
    assert "## Linked Tasks" not in md


def test_build_story_md_metadata_comment_block():
    md, _ = build_story_md(123, SAMPLE_FIELDS, parent_id=None, child_tasks=[])
    assert "<!-- story_context metadata" in md
    assert "id: 123" in md
    assert "type: User Story" in md


def test_build_story_md_no_description_shows_placeholder():
    fields = {**SAMPLE_FIELDS, "System.Description": None}
    md, _ = build_story_md(123, fields, parent_id=None, child_tasks=[])
    assert "No description provided" in md


# ---------------------------------------------------------------------------
# build_refresh_meta_json
# ---------------------------------------------------------------------------

def test_build_refresh_meta_records_methods():
    log = [
        {"field": "System.Description", "method": "markitdown"},
        {"field": "Microsoft.VSTS.Common.AcceptanceCriteria", "method": "fallback", "fallback_reason": "err"},
    ]
    meta = build_refresh_meta_json(123, "2026-04-06T15:00:00Z", log)
    assert meta["story_id"] == 123
    assert meta["fetched_at"] == "2026-04-06T15:00:00Z"
    assert len(meta["conversions"]) == 2
    assert meta["conversions"][1]["fallback_reason"] == "err"


# ---------------------------------------------------------------------------
# html_to_plain_fallback (utils)
# ---------------------------------------------------------------------------

def test_html_to_plain_fallback_strips_tags():
    result = html_to_plain_fallback("<p>Hello <b>world</b></p>")
    assert "<" not in result
    assert "Hello" in result
    assert "world" in result


def test_html_to_plain_fallback_preserves_br_as_newline():
    result = html_to_plain_fallback("Line 1<br/>Line 2")
    assert "Line 1" in result
    assert "Line 2" in result
    assert "\n" in result


def test_html_to_plain_fallback_collapses_excessive_newlines():
    result = html_to_plain_fallback("<p>A</p><p>B</p><p>C</p>")
    # Should not have 3+ consecutive newlines
    assert "\n\n\n" not in result


def test_html_to_plain_fallback_unescapes_entities():
    result = html_to_plain_fallback("&lt;tag&gt; &amp; &quot;quoted&quot;")
    assert "<tag>" in result
    assert "&" in result
    assert '"quoted"' in result
