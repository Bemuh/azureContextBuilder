"""CLI dispatcher for story_context.

Usage: py -m story_context <command> [options]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import ado
from .config import StoryContextError, corpus_dir, digest_path, index_path
from .config import load_yaml, save_yaml
from . import fetcher
from .registry import (
    Registry,
    add_entries,
    filter_ids,
    filter_ids_by_epic,
    get_registered_ids,
    load_registry,
    mark_refreshed,
    save_registry,
)
from .renderer import (
    build_refresh_meta_json,
    build_relations_json,
    build_story_json,
    build_story_md,
)
from .digest import generate_digest, save_digest
from .builder import build_context_bundle
from .utils import now_iso


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_ids(raw: str) -> list[int]:
    """Parse comma-separated IDs string into sorted unique int list."""
    try:
        ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"IDs must be comma-separated integers: {exc}"
        ) from exc
    if not ids:
        raise argparse.ArgumentTypeError("At least one ID is required.")
    return sorted(set(ids))


def _add_profile_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", default=None, help="Profile name from config/profiles.yml")
    parser.add_argument("--profiles-file", default=None, help="Custom profiles file path")
    parser.add_argument("--chunk-size", type=int, default=200, help="ADO batch size (default 200)")
    parser.add_argument("--debug", action="store_true", help="Verbose ADO logging")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="story_context",
        description="Download Azure DevOps stories into an organized Markdown corpus.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # -- list-stories -------------------------------------------------------
    ls = subparsers.add_parser("list-stories", help="List selectable parent stories")
    _add_profile_flags(ls)
    ls.add_argument("--area", required=True, help="Area path filter")
    ls.add_argument("--iteration", required=True, help="Iteration path filter")
    ls.add_argument("--parent-epic", type=int, default=None,
                    help="Filter to stories under this epic ID")
    ls.add_argument("--format", choices=["json", "tsv"], default="tsv",
                    help="Output format (default: tsv)")

    # -- register -----------------------------------------------------------
    reg = subparsers.add_parser("register", help="Register stories for tracking")
    _add_profile_flags(reg)
    reg.add_argument("--area", required=True, help="Area path filter")
    reg.add_argument("--iteration", required=True, help="Iteration path filter")
    id_group = reg.add_mutually_exclusive_group(required=True)
    id_group.add_argument("--ids", default=None, help="Comma-separated story IDs")
    id_group.add_argument("--parent-epic", type=int, default=None,
                          help="Auto-discover stories under this epic")

    # -- refresh ------------------------------------------------------------
    ref = subparsers.add_parser("refresh", help="Refresh registered stories")
    _add_profile_flags(ref)
    ref.add_argument("--ids", default=None, help="Comma-separated IDs (default: all registered)")

    # -- build-context ------------------------------------------------------
    bc = subparsers.add_parser("build-context", help="Build agent-ready context bundle")
    _add_profile_flags(bc)
    id_bc = bc.add_mutually_exclusive_group(required=True)
    id_bc.add_argument("--ids", default=None, help="Comma-separated story IDs")
    id_bc.add_argument("--epic", type=int, default=None,
                       help="Include all stories registered under this epic")
    bc.add_argument("--output", required=True, help="Output .md file path")

    return parser


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def cmd_list_stories(args, profile: dict) -> int:
    org, project = profile["org"], profile["project"]
    debug = 1 if args.debug else 0
    stories = fetcher.list_stories(
        org, project, args.area, args.iteration,
        chunk_size=args.chunk_size, debug=debug,
        parent_epic_id=args.parent_epic,
    )
    if not stories:
        print("No stories found matching the given filters.")
        return 0

    if args.format == "json":
        print(json.dumps(stories, indent=2, ensure_ascii=False, default=str))
    else:
        # TSV output
        print("ID\tTitle\tType\tState\tAreaPath\tIterationPath")
        for item in stories:
            f = item.get("fields", {})
            row = [
                str(item.get("id", "")),
                f.get("System.Title", ""),
                f.get("System.WorkItemType", ""),
                f.get("System.State", ""),
                f.get("System.AreaPath", ""),
                f.get("System.IterationPath", ""),
            ]
            print("\t".join(row))
    return 0


def cmd_register(args, profile: dict) -> int:
    org, project = profile["org"], profile["project"]
    debug = 1 if args.debug else 0
    profile_name = profile["name"]
    parent_epic_id: int | None = None

    if args.parent_epic is not None:
        # Auto-discover stories under the epic
        parent_epic_id = args.parent_epic
        items = fetcher.list_stories(
            org, project, args.area, args.iteration,
            chunk_size=args.chunk_size, debug=debug,
            parent_epic_id=parent_epic_id,
        )
        if not items:
            print(f"No stories found under epic #{parent_epic_id} "
                  f"in area '{args.area}', iteration '{args.iteration}'.")
            return 1
    else:
        # Explicit IDs
        requested_ids = _parse_ids(args.ids)
        items = fetcher.fetch_stories_by_ids(
            org, requested_ids, chunk_size=args.chunk_size, debug=debug,
        )
        # Check for IDs not returned by ADO
        returned_ids = {item.get("id") for item in items}
        missing = [i for i in requested_ids if i not in returned_ids]
        if missing:
            print(f"WARNING: IDs not found in ADO: {', '.join(str(i) for i in missing)} "
                  "— verify they exist and are accessible.")

    registry = load_registry(profile_name)
    new_ids, existing_ids = add_entries(registry, items, parent_epic_id=parent_epic_id)
    save_registry(registry, profile_name)

    print(f"Registered {len(new_ids)} new stories ({len(existing_ids)} already existed).")
    if new_ids:
        print(f"  New: {', '.join(str(i) for i in sorted(new_ids))}")

    # Generate project digest on first run for this profile
    d_path = digest_path(profile_name)
    if not os.path.exists(d_path):
        content = generate_digest(profile_name)
        save_digest(content, profile_name)
        print(f"Project digest generated at {d_path}")

    print(f"\nRun 'py -m story_context refresh --profile {profile_name}' to download content.")
    return 0


def cmd_refresh(args, profile: dict) -> int:
    org, project = profile["org"], profile["project"]
    debug = 1 if args.debug else 0
    profile_name = profile["name"]

    registry = load_registry(profile_name)
    if args.ids:
        target_ids = _parse_ids(args.ids)
        target_ids = filter_ids(registry, target_ids)
    else:
        target_ids = get_registered_ids(registry)

    if not target_ids:
        print("No stories to refresh. Register stories first.")
        return 0

    succeeded: list[int] = []
    failed: list[tuple[int, str]] = []

    for story_id in target_ids:
        try:
            snapshot = fetcher.build_story_snapshot(
                org, story_id, chunk_size=args.chunk_size, debug=debug,
            )
        except Exception as exc:  # noqa: BLE001
            failed.append((story_id, str(exc)[:300]))
            print(f"  FAILED #{story_id}: {exc}")
            continue

        fetched_at = now_iso()
        fields = snapshot["fields"]
        parent_id = snapshot["parent_id"]
        child_tasks = snapshot["child_tasks"]

        # Render corpus files
        story_md, conversion_log = build_story_md(
            story_id, fields, parent_id, child_tasks,
            org=org, project=project, fetched_at=fetched_at,
        )
        story_json = build_story_json(story_id, fields, parent_id, child_tasks, fetched_at)
        relations_json = build_relations_json(story_id, parent_id, child_tasks)
        refresh_meta = build_refresh_meta_json(story_id, fetched_at, conversion_log)

        # Write corpus files
        c_dir = corpus_dir(profile_name, story_id)
        os.makedirs(c_dir, exist_ok=True)

        with open(os.path.join(c_dir, "story.md"), "w", encoding="utf-8") as fh:
            fh.write(story_md)
        with open(os.path.join(c_dir, "story.json"), "w", encoding="utf-8") as fh:
            json.dump(story_json, fh, indent=2, ensure_ascii=False, default=str)
        with open(os.path.join(c_dir, "relations.json"), "w", encoding="utf-8") as fh:
            json.dump(relations_json, fh, indent=2, ensure_ascii=False, default=str)
        with open(os.path.join(c_dir, "refresh_meta.json"), "w", encoding="utf-8") as fh:
            json.dump(refresh_meta, fh, indent=2, ensure_ascii=False, default=str)

        mark_refreshed(registry, story_id, fetched_at)
        succeeded.append(story_id)
        title = fields.get("System.Title", "")
        print(f"  OK #{story_id}: {title}")

    save_registry(registry, profile_name)

    # Rebuild index
    _rebuild_index(registry, profile_name)

    # Check for orphan corpus dirs (O1)
    _warn_orphan_corpus(registry, profile_name)

    # Summary
    print(f"\nRefreshed {len(succeeded)} stories.")
    if failed:
        print(f"Failed: {len(failed)} stories:")
        for sid, reason in failed:
            print(f"  #{sid}: {reason[:100]}")
        return 1
    return 0


def _rebuild_index(registry: Registry, profile_name: str) -> None:
    """Full rebuild of index/<profile>.json from the registry."""
    entries = []
    for story_id in sorted(registry.entries):
        e = registry.entries[story_id]
        entries.append({
            "id": e.id,
            "title": e.title,
            "state": e.state,
            "type": e.type,
            "parent_epic_id": e.parent_epic_id,
            "last_refreshed_at": e.last_refreshed_at,
        })
    idx_path = index_path(profile_name)
    os.makedirs(os.path.dirname(idx_path), exist_ok=True)
    with open(idx_path, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)


def _warn_orphan_corpus(registry: Registry, profile_name: str) -> None:
    """Warn about corpus directories that don't match any registered ID."""
    from .config import DATA_ROOT
    corpus_root = os.path.join(DATA_ROOT, "corpus", profile_name)
    if not os.path.isdir(corpus_root):
        return
    registered = set(registry.entries.keys())
    orphans: list[int] = []
    for name in os.listdir(corpus_root):
        try:
            sid = int(name)
        except ValueError:
            continue
        if sid not in registered:
            orphans.append(sid)
    if orphans:
        print(f"\nOrphan corpus dirs detected: {', '.join(str(o) for o in sorted(orphans))}")
        print("These story IDs are no longer registered. "
              "You can safely delete their corpus directories.")


def cmd_build_context(args, profile: dict) -> int:
    profile_name = profile["name"]
    registry = load_registry(profile_name)

    if args.epic is not None:
        story_ids = filter_ids_by_epic(registry, args.epic)
    else:
        story_ids = _parse_ids(args.ids)
        story_ids = filter_ids(registry, story_ids)

    manifest = build_context_bundle(profile_name, story_ids, args.output)

    n_included = len(manifest["included"])
    n_missing = len(manifest["missing"])
    print(f"Bundle written to {args.output}")
    print(f"  Stories: {n_included} included, {n_missing} missing")
    if manifest["missing"]:
        print(f"  Missing: {', '.join(str(i) for i in manifest['missing'])}")
    return 0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    try:
        ado.check_keys()

        from .config import get_profile
        profile = get_profile(args.profile, args.profiles_file)

        dispatch = {
            "list-stories": cmd_list_stories,
            "register": cmd_register,
            "refresh": cmd_refresh,
            "build-context": cmd_build_context,
        }

        handler = dispatch.get(args.command)
        if handler is None:
            parser.print_help()
            return 1

        return handler(args, profile)

    except StoryContextError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ado.AdoError as exc:
        print(f"ADO Error: {exc}", file=sys.stderr)
        return 1
    except argparse.ArgumentTypeError as exc:
        print(f"Argument error: {exc}", file=sys.stderr)
        return 1
