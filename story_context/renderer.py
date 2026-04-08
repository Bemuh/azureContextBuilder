"""Story corpus file builders and markitdown integration."""
from __future__ import annotations

import sys
from typing import Any

from .utils import has_html_tags, html_to_plain_fallback, now_iso


# ---------------------------------------------------------------------------
# HTML → Markdown conversion
# ---------------------------------------------------------------------------

def _try_markitdown(html: str) -> tuple[str, str, str | None]:
    """Attempt to convert HTML to Markdown using markitdown.

    Returns (converted_text, method, fallback_reason) where method is one of:
    "markitdown" | "fallback"
    fallback_reason is set when falling back due to a non-ImportError exception.
    """
    try:
        from markitdown import MarkItDown  # type: ignore
        md = MarkItDown()
        result = md.convert_text(html, "html")
        return result.text_content, "markitdown", None
    except ImportError:
        return html_to_plain_fallback(html), "fallback", None
    except Exception as exc:  # noqa: BLE001
        reason = str(exc)[:200]
        print(
            f"[story_context] markitdown raised {type(exc).__name__}: {reason}",
            file=sys.stderr,
        )
        return html_to_plain_fallback(html), "fallback", reason


def render_field_md(value: Any, field_name: str) -> tuple[str, str, str | None]:
    """Convert a raw ADO field value to Markdown.

    Returns (rendered_text, method, fallback_reason).
    method: "empty" | "plain" | "markitdown" | "fallback"
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return "", "empty", None

    text = str(value)

    if not has_html_tags(text):
        return text, "plain", None

    converted, method, reason = _try_markitdown(text)
    return converted, method, reason


# ---------------------------------------------------------------------------
# story.md rendering
# ---------------------------------------------------------------------------

def _format_identity(value: Any) -> str:
    """Extract display name from an ADO identity dict or return string as-is."""
    if isinstance(value, dict):
        return value.get("displayName") or value.get("uniqueName") or str(value)
    return str(value) if value is not None else ""


def _format_date(value: Any) -> str:
    if not value:
        return ""
    s = str(value)
    return s[:10] if len(s) >= 10 else s


def build_story_md(
    story_id: int,
    fields: dict,
    parent_id: int | None,
    child_tasks: list[dict],
    org: str = "",
    project: str = "",
    fetched_at: str = "",
) -> tuple[str, list[dict]]:
    """Render story.md content from raw ADO fields.

    Returns (markdown_text, conversion_log).
    conversion_log entries: {"field": str, "method": str, "fallback_reason": str|None}
    """
    conversion_log: list[dict] = []
    fetched_at = fetched_at or now_iso()

    def render(field_ref: str) -> str:
        raw = fields.get(field_ref)
        text, method, reason = render_field_md(raw, field_ref)
        entry: dict = {"field": field_ref, "method": method}
        if reason:
            entry["fallback_reason"] = reason
        conversion_log.append(entry)
        return text

    title = fields.get("System.Title", f"Story {story_id}")
    wi_type = fields.get("System.WorkItemType", "")
    state = fields.get("System.State", "")
    area_path = fields.get("System.AreaPath", "")
    iteration_path = fields.get("System.IterationPath", "")
    tags = fields.get("System.Tags", "") or ""
    created_by = _format_identity(fields.get("System.CreatedBy"))
    created_date = _format_date(fields.get("System.CreatedDate"))
    changed_by = _format_identity(fields.get("System.ChangedBy"))
    changed_date = _format_date(fields.get("System.ChangedDate"))

    description_md = render("System.Description")
    vsts_ac_md = render("Microsoft.VSTS.Common.AcceptanceCriteria")
    custom_ac_md = render("Custom.AcceptanceCriteria")

    ado_url = (
        f"https://dev.azure.com/{org}/{project}/_workitems/edit/{story_id}"
        if org and project
        else f"ADO work item #{story_id}"
    )

    lines: list[str] = []

    # --- Metadata comment block (machine-readable) ---
    lines += [
        "<!-- story_context metadata",
        f"id: {story_id}",
        f"type: {wi_type}",
        f"state: {state}",
        f"area_path: {area_path}",
        f"iteration_path: {iteration_path}",
        f"fetched_at: {fetched_at}",
        "-->",
        "",
    ]

    # --- Title ---
    lines += [f"# [{story_id}] {title}", ""]

    # --- Metadata table ---
    lines += ["## Metadata", ""]
    lines += ["| Field | Value |", "|-------|-------|"]
    lines.append(f"| ID | {story_id} |")
    lines.append(f"| Type | {wi_type} |")
    lines.append(f"| State | {state} |")
    lines.append(f"| Area | {area_path} |")
    lines.append(f"| Iteration | {iteration_path} |")
    if tags:
        lines.append(f"| Tags | {tags} |")
    if created_by:
        lines.append(f"| Created By | {created_by} |")
    if created_date:
        lines.append(f"| Created Date | {created_date} |")
    if changed_by:
        lines.append(f"| Changed By | {changed_by} |")
    if changed_date:
        lines.append(f"| Changed Date | {changed_date} |")
    lines.append("")

    # --- Acceptance Criteria (VSTS) ---
    lines += ["## Acceptance Criteria", ""]
    if vsts_ac_md:
        lines += [vsts_ac_md, ""]
    else:
        lines += ["_No acceptance criteria defined._", ""]

    # --- Additional Acceptance Criteria (Custom) — omit section if empty ---
    if custom_ac_md:
        lines += ["## Additional Acceptance Criteria", "", custom_ac_md, ""]

    # --- Description ---
    lines += ["## Description", ""]
    if description_md:
        lines += [description_md, ""]
    else:
        lines += ["_No description provided._", ""]

    # --- Linked Tasks — omit section if no child tasks ---
    if child_tasks:
        lines += ["## Linked Tasks", ""]
        lines += ["| ID | Title | State |", "|----|-------|-------|"]
        for task in child_tasks:
            t_id = task.get("id", "")
            t_title = task.get("title", "").replace("|", "\\|")
            t_state = task.get("state", "")
            lines.append(f"| {t_id} | {t_title} | {t_state} |")
        lines.append("")

    # --- Source traceability ---
    lines += ["## Source", ""]
    lines.append(f"- ADO URL: {ado_url}")
    if parent_id is not None:
        lines.append(f"- Parent: #{parent_id}")
    lines.append(f"- Fetched: {fetched_at}")

    # Conversion methods summary
    non_empty = [e for e in conversion_log if e["method"] != "empty"]
    if non_empty:
        methods_str = ", ".join(
            f"{e['field'].rsplit('.', 1)[-1]} ({e['method']})" for e in non_empty
        )
        lines.append(f"- Fields: {methods_str}")
    lines.append("")

    return "\n".join(lines), conversion_log


# ---------------------------------------------------------------------------
# Corpus file builders
# ---------------------------------------------------------------------------

def build_story_json(
    story_id: int,
    fields: dict,
    parent_id: int | None,
    child_tasks: list[dict],
    fetched_at: str,
) -> dict:
    """Lossless raw snapshot for traceability and deterministic rebuilds."""
    return {
        "story_id": story_id,
        "fetched_at": fetched_at,
        "fields": fields,
        "parent_id": parent_id,
        "child_tasks": child_tasks,
    }


def build_relations_json(
    story_id: int,
    parent_id: int | None,
    child_tasks: list[dict],
) -> dict:
    return {
        "story_id": story_id,
        "parent": parent_id,
        "children": child_tasks,
    }


def build_refresh_meta_json(
    story_id: int,
    fetched_at: str,
    conversion_log: list[dict],
) -> dict:
    return {
        "story_id": story_id,
        "fetched_at": fetched_at,
        "conversions": conversion_log,
    }
