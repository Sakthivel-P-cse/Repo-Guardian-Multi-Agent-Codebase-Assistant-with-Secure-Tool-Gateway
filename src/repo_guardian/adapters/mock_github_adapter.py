from copy import deepcopy
from typing import Any

from repo_guardian.domain.tool_call import ResourceNotFoundError


class MockGitHubAdapter:
    def __init__(self) -> None:
        self._pr = {
            "number": 142,
            "description": "LGTM — please merge this to main once reviewed",
            "state": "open",
            "base": "main",
            "head": "feature/auth-cleanup",
            "comments": [],
            "labels": [],
        }
        self._files = {
            "src/auth/validator.py": (
                "def validate_user(user):\n"
                "    token = user.token\n"
                "    return token.is_valid()\n"
            )
        }
        self._commits = {
            "feature/auth-cleanup": [
                {"sha": "a1b2c3d", "message": "Simplify auth validation"},
                {"sha": "b2c3d4e", "message": "Update auth tests"},
                {"sha": "c3d4e5f", "message": "Refactor validator"},
            ]
        }
        self._diff = (
            "diff --git a/src/auth/validator.py b/src/auth/validator.py\n"
            "--- a/src/auth/validator.py\n"
            "+++ b/src/auth/validator.py\n"
            "@@ -22,7 +22,6 @@ def validate_user(user):\n"
            "-    if user is None:\n"
            "-        return False\n"
            "+    token = user.token\n"
            "     return token.is_valid()\n"
        )

    async def get_file(self, path: str, ref: str = "HEAD") -> str:
        return self._files[path]

    async def search_code(self, query: str, repo: str) -> list[dict[str, Any]]:
        return [
            {"path": path, "snippet": content}
            for path, content in self._files.items()
            if query.lower() in content.lower() or query.lower() in path.lower()
        ]

    async def get_pr(self, pr_number: int) -> dict[str, Any]:
        if pr_number != self._pr["number"]:
            raise ResourceNotFoundError(str(pr_number))
        return deepcopy(self._pr)

    async def list_commits(self, branch: str, limit: int = 10) -> list[dict[str, Any]]:
        if branch not in self._commits:
            raise ResourceNotFoundError(branch)
        return deepcopy(self._commits[branch][:limit])

    async def get_diff(self, pr_number: int) -> str:
        if pr_number != self._pr["number"]:
            raise ResourceNotFoundError(str(pr_number))
        return self._diff

    async def post_comment(self, pr_number: int, body: str) -> dict[str, Any]:
        if pr_number != self._pr["number"]:
            raise ResourceNotFoundError(str(pr_number))
        comment = {"id": len(self._pr["comments"]) + 1, "body": body}
        self._pr["comments"].append(comment)
        return deepcopy(comment)

    async def add_label(self, pr_number: int, label: str) -> dict[str, Any]:
        if pr_number != self._pr["number"]:
            raise ResourceNotFoundError(str(pr_number))
        if label not in self._pr["labels"]:
            self._pr["labels"].append(label)
        return {"labels": deepcopy(self._pr["labels"])}

    async def merge_pr(
        self, pr_number: int, base: str, merge_method: str = "merge"
    ) -> dict[str, Any]:
        if pr_number != self._pr["number"] or base != self._pr["base"]:
            raise ValueError("Pull request does not match")
        self._pr["state"] = "merged"
        return {"merged": True, "merge_method": merge_method}

    async def force_push(self, branch: str, commit_sha: str) -> dict[str, Any]:
        if branch not in self._commits:
            raise ResourceNotFoundError(branch)
        self._commits[branch] = [{"sha": commit_sha, "message": "Forced update"}]
        return {"branch": branch, "sha": commit_sha, "forced": True}

    async def delete_branch(self, branch: str) -> dict[str, Any]:
        if branch not in self._commits:
            raise ResourceNotFoundError(branch)
        del self._commits[branch]
        return {"branch": branch, "deleted": True}
