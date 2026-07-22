import pytest

from repo_guardian.domain.tool_call import ToolCall
from repo_guardian.gateway.classifier import ContextualRiskClassifier


def call(tool_name, **parameters):
    return ToolCall(tool_name, parameters, "repo_ops", "run-1")


@pytest.mark.parametrize(
    ("tool_name", "parameters"),
    [
        ("get_file", {"path": "README.md"}),
        ("search_code", {"query": "token", "repo": "owner/repo"}),
        ("get_pr", {"pr_number": 142}),
        ("list_commits", {"branch": "main"}),
        ("get_diff", {"pr_number": 142}),
    ],
)
def test_read_only_tools_are_tier1(tool_name, parameters):
    assert ContextualRiskClassifier().classify(call(tool_name, **parameters)) == "tier1"


@pytest.mark.parametrize("tool_name", ["post_comment", "add_label", "create_draft"])
def test_review_writes_are_tier2(tool_name):
    assert ContextualRiskClassifier().classify(call(tool_name)) == "tier2"


@pytest.mark.parametrize("base", ["main", "master"])
def test_merge_to_protected_base_is_tier3(base):
    assert ContextualRiskClassifier().classify(call("merge_pr", base=base)) == "tier3"


def test_merge_to_feature_base_is_tier2():
    assert ContextualRiskClassifier().classify(call("merge_pr", base="feature-x")) == "tier2"


@pytest.mark.parametrize("parameters", [{}, {"branch": "feature-x"}])
def test_force_push_is_always_tier3(parameters):
    assert ContextualRiskClassifier().classify(call("force_push", **parameters)) == "tier3"


@pytest.mark.parametrize("branch", ["main", "master", "develop"])
def test_delete_protected_branch_is_tier3(branch):
    assert ContextualRiskClassifier().classify(call("delete_branch", branch=branch)) == "tier3"


def test_delete_feature_branch_is_tier2():
    assert ContextualRiskClassifier().classify(call("delete_branch", branch="feature-x")) == "tier2"


def test_unknown_tool_fails_secure_to_tier3():
    assert ContextualRiskClassifier().classify(call("download_secrets")) == "tier3"
