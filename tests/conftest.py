"""Shared fixtures for story_context tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# pytest markers
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: opt-in live Azure tests (set SC_LIVE_TESTS=1 and SC_LIVE_PROFILE=<name>)",
    )


@pytest.fixture(autouse=True)
def skip_live(request):
    """Auto-skip tests marked @pytest.mark.live unless SC_LIVE_TESTS=1."""
    if request.node.get_closest_marker("live"):
        if not os.environ.get("SC_LIVE_TESTS"):
            pytest.skip("Set SC_LIVE_TESTS=1 and SC_LIVE_PROFILE=<name> to run live tests.")


# ---------------------------------------------------------------------------
# Common fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_data_root(tmp_path, monkeypatch):
    """Redirect story_context.config.DATA_ROOT to a temp dir."""
    import story_context.config as cfg
    monkeypatch.setattr(cfg, "DATA_ROOT", str(tmp_path / "story_context_data"))
    return tmp_path


@pytest.fixture
def sample_fields() -> dict:
    """Full STORY_FIELDS dict with HTML in Description/AC."""
    return {
        "System.Id": 123,
        "System.Title": "Add login flow",
        "System.WorkItemType": "User Story",
        "System.State": "Active",
        "System.AreaPath": "Project\\Area\\Backend",
        "System.IterationPath": "Project\\Sprint 08",
        "System.Tags": "auth; mvp",
        "System.Parent": 500,
        "System.CreatedBy": {"displayName": "Jane Smith", "uniqueName": "jane@example.com"},
        "System.CreatedDate": "2026-03-01T10:00:00Z",
        "System.ChangedBy": {"displayName": "John Doe", "uniqueName": "john@example.com"},
        "System.ChangedDate": "2026-04-01T10:00:00Z",
        "System.Description": "<div>Login flow <b>description</b></div>",
        "Microsoft.VSTS.Common.AcceptanceCriteria": "<p>Must handle SSO</p>",
        "Custom.AcceptanceCriteria": None,
    }
