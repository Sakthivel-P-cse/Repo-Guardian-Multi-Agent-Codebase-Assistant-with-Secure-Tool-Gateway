import asyncio
import base64
import json
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from repo_guardian.domain.tool_call import ResourceNotFoundError


class GitHubAdapterPort(Protocol):
    async def get_file(self, path: str, ref: str = "HEAD") -> str: ...

    async def search_code(self, query: str, repo: str) -> list[dict[str, Any]]: ...

    async def get_pr(self, pr_number: int) -> dict[str, Any]: ...

    async def list_commits(self, branch: str, limit: int = 10) -> list[dict[str, Any]]: ...

    async def get_diff(self, pr_number: int) -> str: ...

    async def post_comment(self, pr_number: int, body: str) -> dict[str, Any]: ...

    async def add_label(self, pr_number: int, label: str) -> dict[str, Any]: ...

    async def merge_pr(
        self, pr_number: int, base: str, merge_method: str = "merge"
    ) -> dict[str, Any]: ...

    async def force_push(self, branch: str, commit_sha: str) -> dict[str, Any]: ...

    async def delete_branch(self, branch: str) -> dict[str, Any]: ...


class GitHubAdapter:
    def __init__(self, token: str, repo: str, api_url: str = "https://api.github.com") -> None:
        self._token = token
        self._repo = repo
        self._api_url = api_url.rstrip("/")

    async def get_file(self, path: str, ref: str = "HEAD") -> str:
        data = await self._request("GET", f"/repos/{self._repo}/contents/{quote(path)}?ref={quote(ref)}")
        return base64.b64decode(data["content"]).decode()

    async def search_code(self, query: str, repo: str) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", f"/search/code?{urlencode({'q': f'{query} repo:{repo}'})}"
        )
        return list(data.get("items", []))

    async def get_pr(self, pr_number: int) -> dict[str, Any]:
        pr, comments = await asyncio.gather(
            self._request("GET", f"/repos/{self._repo}/pulls/{pr_number}"),
            self._request("GET", f"/repos/{self._repo}/issues/{pr_number}/comments"),
        )
        return {
            "number": pr["number"],
            "description": pr.get("body", ""),
            "state": "merged" if pr.get("merged") else pr["state"],
            "base": pr["base"]["ref"],
            "head": pr["head"]["ref"],
            "comments": comments,
            "labels": [label["name"] for label in pr.get("labels", [])],
        }

    async def list_commits(self, branch: str, limit: int = 10) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", f"/repos/{self._repo}/commits?{urlencode({'sha': branch, 'per_page': limit})}"
        )
        return [
            {"sha": item["sha"], "message": item["commit"]["message"]}
            for item in data
        ]

    async def get_diff(self, pr_number: int) -> str:
        return await self._request(
            "GET",
            f"/repos/{self._repo}/pulls/{pr_number}",
            accept="application/vnd.github.v3.diff",
        )

    async def post_comment(self, pr_number: int, body: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/repos/{self._repo}/issues/{pr_number}/comments", {"body": body}
        )

    async def add_label(self, pr_number: int, label: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/repos/{self._repo}/issues/{pr_number}/labels", {"labels": [label]}
        )

    async def merge_pr(
        self, pr_number: int, base: str, merge_method: str = "merge"
    ) -> dict[str, Any]:
        pr = await self.get_pr(pr_number)
        if pr["base"] != base:
            raise ValueError("Pull request base does not match the requested base")
        return await self._request(
            "PUT", f"/repos/{self._repo}/pulls/{pr_number}/merge", {"merge_method": merge_method}
        )

    async def force_push(self, branch: str, commit_sha: str) -> dict[str, Any]:
        return await self._request(
            "PATCH",
            f"/repos/{self._repo}/git/refs/heads/{quote(branch)}",
            {"sha": commit_sha, "force": True},
        )

    async def delete_branch(self, branch: str) -> dict[str, Any]:
        await self._request("DELETE", f"/repos/{self._repo}/git/refs/heads/{quote(branch)}")
        return {"branch": branch, "deleted": True}

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        accept: str = "application/vnd.github+json",
    ) -> Any:
        return await asyncio.to_thread(self._request_sync, method, path, body, accept)

    def _request_sync(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        accept: str,
    ) -> Any:
        payload = json.dumps(body).encode() if body is not None else None
        request = Request(
            f"{self._api_url}{path}",
            data=payload,
            method=method,
            headers={
                "Accept": accept,
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as error:
            if error.code == 404:
                raise ResourceNotFoundError(path) from error
            raise RuntimeError(f"GitHub API request failed with status {error.code}") from error
        if not raw:
            return {}
        if accept.endswith(".diff"):
            return raw.decode()
        return json.loads(raw)
