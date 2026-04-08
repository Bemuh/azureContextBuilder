import json
import os

# ---------------------------------------------------------------------------
# Path resolution — package-relative so the whole folder can be moved freely.
# ---------------------------------------------------------------------------
_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.path.join(_PACKAGE_DIR, "story_context_data")
_DEFAULT_PROFILES = os.path.join(_PACKAGE_DIR, "config", "profiles.yml")


class StoryContextError(Exception):
    pass


# ---------------------------------------------------------------------------
# YAML helpers (mirrors sync/config.py pattern)
# ---------------------------------------------------------------------------

def load_yaml(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        try:
            import yaml
        except ImportError:
            yaml = None
        if yaml is not None:
            return yaml.safe_load(fh)
        text = fh.read()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise StoryContextError(
                "PyYAML is required to parse non-JSON YAML files."
            ) from exc


def save_yaml(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        try:
            import yaml
        except ImportError:
            yaml = None
        if yaml is not None:
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=False)
        else:
            json.dump(data, fh, indent=2, ensure_ascii=True)


# ---------------------------------------------------------------------------
# Profile loading — reads the same config/profiles.yml used by sync.
# Only extracts the fields story_context actually needs; no migration logic.
# ---------------------------------------------------------------------------

def _flatten_profile(name: str, v2: dict) -> dict:
    ado = v2.get("ado") or {}
    paths = v2.get("paths") or {}
    org_url = ado.get("org_url", "")
    # Extract org slug: https://dev.azure.com/myorg -> myorg
    org = org_url.rstrip("/").rsplit("/", 1)[-1] if org_url else ""
    return {
        "name": name,
        "org": org,
        "project": ado.get("project", ""),
        "area_path": paths.get("last_area_path", ""),
        "iteration_path": paths.get("last_iteration_path", ""),
    }


def get_profile(name: str | None, profiles_file: str | None = None) -> dict:
    """Load a profile from config/profiles.yml and return a flat dict.

    Raises StoryContextError if the file is missing, the profile is not found,
    or no profiles are defined.
    """
    path = profiles_file or _DEFAULT_PROFILES
    data = load_yaml(path)
    if not data or "profiles" not in data:
        raise StoryContextError(
            f"Missing or invalid profiles file: {path}\n"
            "Run 'py -m sync setup' to create your profile."
        )
    raw_profiles = data.get("profiles") or {}
    if not raw_profiles:
        raise StoryContextError("No profiles defined in profiles.yml.")

    # Normalize keys: PyYAML loads YAML `null` as Python None.
    # Users pass `--profile null` as a string. Normalize both to strings.
    profiles: dict[str, dict] = {}
    for k, v in raw_profiles.items():
        profiles[str(k) if k is not None else "null"] = v

    if name:
        lookup = name
        if lookup not in profiles:
            raise StoryContextError(
                f"Profile '{lookup}' not found in {path}. "
                f"Available: {', '.join(profiles)}"
            )
        selected = lookup
    else:
        # Fall back to ui.active_profile, then ui.last_used_profile, then first
        ui = data.get("ui") or {}
        active = ui.get("active_profile") or ui.get("last_used_profile")
        if active and str(active) in profiles:
            selected = str(active)
        else:
            selected = next(iter(profiles))

    return _flatten_profile(selected, profiles[selected])


# ---------------------------------------------------------------------------
# Data path helpers — all paths are under DATA_ROOT
# ---------------------------------------------------------------------------

def registry_path(profile_name: str) -> str:
    return os.path.join(DATA_ROOT, "registries", f"{profile_name}.yml")


def digest_path(profile_name: str) -> str:
    return os.path.join(DATA_ROOT, "project_digest", f"{profile_name}.md")


def index_path(profile_name: str) -> str:
    return os.path.join(DATA_ROOT, "index", f"{profile_name}.json")


def corpus_dir(profile_name: str, story_id: int) -> str:
    return os.path.join(DATA_ROOT, "corpus", profile_name, str(story_id))
