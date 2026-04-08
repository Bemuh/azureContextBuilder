"""build-context bundling for story_context."""
from __future__ import annotations

import json
import os

from .config import corpus_dir, digest_path
from .utils import now_iso


def load_story_files(profile_name: str, story_id: int) -> dict | None:
    """Load story.md and refresh_meta.json for a story.

    Returns None if corpus dir does not exist (story never refreshed).
    Only reads the files needed for build-context (N1 decision).
    """
    c_dir = corpus_dir(profile_name, story_id)
    story_md_path = os.path.join(c_dir, "story.md")
    meta_path = os.path.join(c_dir, "refresh_meta.json")

    if not os.path.isdir(c_dir) or not os.path.exists(story_md_path):
        return None

    with open(story_md_path, "r", encoding="utf-8") as fh:
        story_md = fh.read()

    meta: dict = {}
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as fh:
            try:
                meta = json.load(fh)
            except (json.JSONDecodeError, OSError):
                meta = {}

    return {"story_md": story_md, "meta": meta}


def build_manifest(
    profile_name: str,
    story_ids: list[int],
    included_ids: list[int],
    missing_ids: list[int],
    generated_at: str | None = None,
) -> dict:
    return {
        "profile": profile_name,
        "generated_at": generated_at or now_iso(),
        "requested": sorted(story_ids),
        "included": sorted(included_ids),
        "missing": sorted(missing_ids),
    }


def _load_digest(profile_name: str) -> tuple[str, bool]:
    """Return (digest_content, digest_found)."""
    path = digest_path(profile_name)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read(), True
    return "", False


def build_context_bundle(
    profile_name: str,
    story_ids: list[int],
    output_path: str,
) -> dict:
    """Compose a single agent-ready Markdown bundle and write it to output_path.

    Stories are included in ascending ID order.
    Returns the manifest dict.
    """
    generated_at = now_iso()
    sorted_ids = sorted(story_ids)

    digest_content, digest_found = _load_digest(profile_name)

    included_ids: list[int] = []
    missing_ids: list[int] = []
    story_sections: list[str] = []

    for story_id in sorted_ids:
        files = load_story_files(profile_name, story_id)
        if files is None:
            missing_ids.append(story_id)
        else:
            included_ids.append(story_id)
            # Extract title from first heading in story.md
            title = ""
            for line in files["story_md"].splitlines():
                if line.startswith("# ["):
                    title = line[2:].strip()
                    break
            story_sections.append(
                f"# Story #{story_id} — {title}\n\n{files['story_md']}"
            )

    manifest = build_manifest(
        profile_name, story_ids, included_ids, missing_ids, generated_at
    )

    # Build output document
    lines: list[str] = []

    # Machine-readable manifest comment at the top
    lines += [
        "<!-- build_context_manifest",
        f"profile: {profile_name}",
        f"generated_at: {generated_at}",
        f"story_ids: {sorted_ids}",
        f"missing: {missing_ids}",
        "-->",
        "",
    ]

    # Human-readable header
    n_included = len(included_ids)
    n_missing = len(missing_ids)
    missing_note = ""
    if n_missing:
        missing_note = (
            f" {n_missing} missing ({', '.join(str(i) for i in missing_ids)}"
            " — run `story_context refresh` first)"
        )
    lines += [
        "# Context Bundle",
        "",
        f"_Profile: {profile_name} — Generated: {generated_at}_",
        f"_Stories: {n_included} included{missing_note}_",
        "",
        "---",
        "",
    ]

    # Project digest
    lines += ["# Project Digest", ""]
    if digest_found:
        lines += [digest_content, ""]
    else:
        lines += [
            "_Project digest not available. "
            "Run `story_context register` to generate it._",
            "",
        ]

    # Story sections
    for section in story_sections:
        lines += ["---", "", section, ""]

    # Manifest JSON block at end
    lines += [
        "---",
        "",
        "```json",
        json.dumps(manifest, indent=2),
        "```",
        "",
    ]

    output = "\n".join(lines)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(output)

    return manifest
