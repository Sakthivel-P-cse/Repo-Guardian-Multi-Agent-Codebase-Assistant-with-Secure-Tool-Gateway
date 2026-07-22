from typing import Protocol

from repo_guardian.domain.tool_call import RiskTier, ToolCall


class RiskClassifierPort(Protocol):
    def classify(self, call: ToolCall) -> RiskTier: ...


class ContextualRiskClassifier:
    _tier1_tools = {"get_file", "search_code", "get_pr", "list_commits", "get_diff"}
    _tier2_tools = {"post_comment", "add_label", "create_draft"}

    def classify(self, call: ToolCall) -> RiskTier:
        if call.tool_name in self._tier1_tools:
            return "tier1"
        if call.tool_name in self._tier2_tools:
            return "tier2"
        if call.tool_name == "merge_pr":
            return "tier3" if call.parameters.get("base") in {"main", "master"} else "tier2"
        if call.tool_name == "force_push":
            return "tier3"
        if call.tool_name == "delete_branch":
            protected = call.parameters.get("branch") in {"main", "master", "develop"}
            return "tier3" if protected else "tier2"
        return "tier3"
