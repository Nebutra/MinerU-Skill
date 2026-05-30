"""Tests for the optional Roam Research sink.

The Markdown→tree converter is tested directly; delivery is tested with a faked
``roam_client`` SDK so it runs offline without the git-only package installed.
"""

import sys
import types

import pytest

import sinks
from sinks import roam as roam_mod
from sinks.base import ParsedDoc, SinkError


# --------------------------------------------------------------------------- #
# Pure converter
# --------------------------------------------------------------------------- #
def test_md_to_roam_tree_nests_under_headings():
    tree = roam_mod.md_to_roam_tree(
        "# H1\n\nintro\n\n## H2\n\ndetail line\n"
    )
    assert tree[0]["string"] == "H1" and tree[0]["heading"] == 1
    kids = tree[0]["children"]
    assert kids[0] == {"string": "intro", "children": []}
    h2 = kids[1]
    assert h2["string"] == "H2" and h2["heading"] == 2
    assert h2["children"][0]["string"] == "detail line"


def test_md_to_roam_tree_caps_heading_level_at_3():
    tree = roam_mod.md_to_roam_tree("##### deep\n")
    assert tree[0]["heading"] == 3


def test_tree_to_actions_uses_temp_uids_for_nesting():
    tree = roam_mod.md_to_roam_tree("# H\n\nchild\n")
    import itertools
    counter = itertools.count(1)
    actions = roam_mod.tree_to_actions(tree, "PAGE", lambda: f"mu{next(counter):07d}")
    assert actions[0]["block"]["string"] == "H"
    assert actions[0]["location"]["parent-uid"] == "PAGE"
    parent_uid = actions[0]["block"]["uid"]
    assert actions[1]["location"]["parent-uid"] == parent_uid  # child nests under heading
    assert actions[1]["block"]["string"] == "child"


# --------------------------------------------------------------------------- #
# Delivery via faked SDK
# --------------------------------------------------------------------------- #
class _FakeClient:
    def __init__(self):
        self.calls = []

    def call(self, path, method, body):
        self.calls.append((path, method, body))
        return {"success": True}


@pytest.fixture
def fake_sdk(monkeypatch):
    client = _FakeClient()
    created = []
    mod = types.ModuleType("roam_client")
    client_mod = types.ModuleType("roam_client.client")
    client_mod.initialize_graph = lambda cfg: client
    client_mod.create_page = lambda c, page: created.append(page)
    mod.client = client_mod
    monkeypatch.setitem(sys.modules, "roam_client", mod)
    monkeypatch.setitem(sys.modules, "roam_client.client", client_mod)
    return client, created


def test_roam_delivers_via_batch_actions(fake_sdk, monkeypatch):
    client, created = fake_sdk
    monkeypatch.setenv("ROAM_API_TOKEN", "tok")
    monkeypatch.setenv("ROAM_GRAPH_NAME", "MyGraph")

    doc = ParsedDoc(title="Paper", markdown="# Heading\n\nbody\n")
    res = sinks.get_sink("roam").deliver(doc)

    assert res.ok and "MyGraph" in res.url
    assert created == [{"page": {"title": "Paper"}}]
    assert len(client.calls) == 1
    path, method, body = client.calls[0]
    assert path == "/api/graph/MyGraph/write" and method == "POST"
    assert body["action"] == "batch-actions"
    assert body["actions"][0]["block"]["string"] == "Heading"


def test_roam_missing_sdk_gives_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "roam_client.client", None)  # force ImportError
    monkeypatch.setenv("ROAM_API_TOKEN", "t")
    monkeypatch.setenv("ROAM_GRAPH_NAME", "g")
    with pytest.raises(SinkError) as exc:
        sinks.get_sink("roam").deliver(ParsedDoc(title="t", markdown="# h\n"))
    assert "roam-client" in str(exc.value)
