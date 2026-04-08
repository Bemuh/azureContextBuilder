"""Project digest generation for story_context."""
from __future__ import annotations

import os

from .config import DATA_ROOT, StoryContextError, digest_path
from .utils import now_iso

# Source files to include in the digest, in priority order.
# Matched case-insensitively against top-level repo files.
DIGEST_SOURCE_FILES = ["README.MD", "PLAN.md", "AGENTS.md"]

DIGEST_EXCLUDED_DIRS = {"keys", ".git", "__pycache__", "story_context_data"}
_EXCLUDED_FILENAMES = {"pattoken.enc", "encryption.key"}


def _is_safe_path(path: str) -> bool:
    """Return False if the path looks like it could contain credentials."""
    norm = os.path.normpath(path).lower()
    parts = norm.replace("\\", "/").split("/")
    for part in parts:
        if part in {"keys"}:
            return False
        if part in _EXCLUDED_FILENAMES:
            return False
    basename = os.path.basename(norm)
    return basename not in _EXCLUDED_FILENAMES


def find_digest_sources(repo_root: str) -> list[tuple[str, str]]:
    """Find DIGEST_SOURCE_FILES at the top level of repo_root.

    Returns list of (filename_as_found, absolute_path) in DIGEST_SOURCE_FILES order.
    Files not present are silently skipped.
    """
    repo_root = os.path.abspath(repo_root)
    try:
        top_level = os.listdir(repo_root)
    except OSError:
        return []

    # Build case-insensitive lookup: lowercase_name -> actual_name
    name_map: dict[str, str] = {f.lower(): f for f in top_level}

    results: list[tuple[str, str]] = []
    for target in DIGEST_SOURCE_FILES:
        actual = name_map.get(target.lower())
        if actual is None:
            continue
        abs_path = os.path.join(repo_root, actual)
        if not os.path.isfile(abs_path):
            continue
        if not _is_safe_path(abs_path):
            continue
        results.append((actual, abs_path))

    return results


def generate_digest(profile_name: str, repo_root: str = ".") -> str:
    """Compose the project digest Markdown string.

    Includes a machine-readable HTML comment header, then one section per
    source file.  Missing files are noted with a placeholder paragraph.
    Warns to stderr if the final content exceeds 50KB.
    """
    generated_at = now_iso()
    sources = find_digest_sources(repo_root)
    found_names = [name for name, _ in sources]

    # Comment header
    sources_list = "\n".join(f"  - {n}" for n in found_names) or "  (none found)"
    header = (
        f"<!-- project_digest\n"
        f"profile: {profile_name}\n"
        f"generated_at: {generated_at}\n"
        f"sources:\n{sources_list}\n"
        f"-->"
    )

    title_line = f"# Project Digest\n\n_Generated: {generated_at} — Profile: {profile_name}_"
    if found_names:
        title_line += f"\n_Sources: {', '.join(found_names)}_"

    sections: list[str] = [header, "", title_line]

    source_map: dict[str, str] = {name: path for name, path in sources}

    for target in DIGEST_SOURCE_FILES:
        actual = next(
            (n for n in found_names if n.lower() == target.lower()), None
        )
        sections.append("\n---\n")
        if actual and actual in source_map:
            with open(source_map[actual], "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            sections.append(f"## {actual}\n\n{content}")
        else:
            sections.append(
                f"## {target}\n\n_{target} not found at project root — omitted._"
            )

    result = "\n".join(sections)

    if len(result) > 50_000:
        kb = len(result) // 1024
        print(
            f"[story_context] Warning: project digest is {kb}KB. "
            "Consider trimming source docs."
        )

    return result


def save_digest(content: str, profile_name: str) -> None:
    path = digest_path(profile_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
