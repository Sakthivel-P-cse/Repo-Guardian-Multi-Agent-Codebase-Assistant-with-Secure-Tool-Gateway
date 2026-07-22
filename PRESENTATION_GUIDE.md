# Repo Guardian — Complete Presentation Guide

## 1. Project Title and One-Line Description

**Repo Guardian** — A multi-agent AI assistant that reviews GitHub pull requests through a secure gateway that blocks dangerous operations.

---

## 2. Problem This Project Solves

Large language models (LLMs) can read code and write reviews, but they cannot be trusted with full GitHub access. If an LLM agent gets confused or is tricked (prompt injection), it could accidentally merge a bad PR, force-push to main, or delete a protected branch. Existing GitHub code-review tools give agents broad API access without fine-grained safety checks. Repo Guardian solves this by putting every tool call through a **security gateway** that classifies risk, checks intent, issues one-time credentials, verifies outcomes, and logs everything.

---

## 3. Main Objective

Build a system where AI agents can safely inspect repositories and write pull-request reviews, but **cannot** perform dangerous operations like merging to main, force-pushing, or deleting protected branches. The gateway acts as a guard that always says "no" to destructive actions, regardless of what the agent requests.

---

## 4. Complete Workflow (Step by Step)

### Step 1: User gives a goal
The user says something like: *"Review PR #142 and tell me if it's safe to merge — do not merge it yourself."* (`src/repo_guardian/entrypoints/run_demo.py`, line 150)

### Step 2: Supervisor plans the work
The `SupervisorAgent` creates a task plan (`TaskGraph`) with 3-4 subtasks:
- **inspect** — assigned to `CodeSearchAgent` (gather evidence)
- **review** — assigned to `ReviewAgent` (draft a review comment)
- **injection_probe** — assigned to `RepoOpsAgent` (optional safety test: try to merge)
- **critic** — assigned to `CriticAgent` (fact-check the final answer)

(`src/repo_guardian/agents/supervisor.py`, lines 139-155, method `_plan()`)

### Step 3: CodeSearchAgent gathers evidence
This agent makes 3 read-only calls through the gateway:
1. `get_pr` — fetches PR metadata (number, description, state, base branch, head branch)
2. `get_diff` — fetches the code changes in the PR
3. `list_commits` — fetches recent commit history on the head branch

(`src/repo_guardian/agents/code_search.py`)

Each call goes through the `SecureToolGateway`. Since these are read operations, the classifier marks them **Tier 1** and they are approved automatically.

### Step 4: Gateway processes each call
For every tool call, the `SecureToolGateway.execute()` method runs this pipeline:
1. **Classify risk** — Assigns Tier 1, 2, or 3 based on tool name and parameters (`src/repo_guardian/gateway/classifier.py`)
2. **Log pending** — Writes "pending" to the SQLite audit log (`src/repo_guardian/gateway/audit.py`)
3. **If Tier 3** — Block immediately, log "blocked", return failure (no token issued, no tool called)
4. **If Tier 2** — Run an LLM-based goal-consistency check to ensure the call matches the user's original goal (`src/repo_guardian/gateway/goal_checker.py`)
5. **Issue scoped token** — Generate a single-use, time-limited (30s), tool-scoped token (`src/repo_guardian/gateway/credential_manager.py`)
6. **Execute tool** — Route to the correct MCP server, which validates the token before calling the GitHub adapter (`src/repo_guardian/mcp_servers/__init__.py`)
7. **Revoke token** — Always revoke in a `finally` block
8. **If Tier 2** — Verify the outcome by reading state back (e.g., re-read the PR to confirm the comment was posted) (`src/repo_guardian/gateway/verifier.py`)
9. **Log decision** — Write final decision to audit log
10. **Return result** — Return `ToolResult` with success and verified flags

(`src/repo_guardian/gateway/gateway.py`, method `execute()`, lines 27-63)

### Step 5: ReviewAgent drafts a comment
The `ReviewAgent` reads the evidence gathered by CodeSearchAgent and asks the LLM to write a concise review comment. It makes **zero** tool calls — it only reads collected evidence and calls the LLM. (`src/repo_guardian/agents/reviewer.py`)

### Step 6: ReviewPublisher posts the comment
The `ReviewPublisher` wraps the drafted comment in a `post_comment` `ToolCall` and executes it through the gateway. Since `post_comment` is **Tier 2**, the gateway:
- Checks that posting a comment is consistent with the user's goal
- Issues a scoped token
- Calls the MCP review server
- Verifies the comment was actually posted by re-reading the PR
- Logs the decision as "approved_logged"

(`src/repo_guardian/agents/reviewer.py`, class `ReviewPublisher`)

### Step 7: RepoOpsAgent runs a safety probe (optional)
If configured, the `RepoOpsAgent` tries to call `merge_pr` with `base="main"`. The gateway classifies this as **Tier 3** and blocks it immediately, demonstrating that even if an agent tries to merge, it cannot. (`src/repo_guardian/agents/repo_ops.py`)

### Step 8: CriticAgent fact-checks the answer
The `CriticAgent` compares the final answer against all collected tool results. For each claim in the answer, it checks whether that claim can be traced back to a specific tool result. If a claim is not grounded in evidence, it flags it. The Supervisor can then ask the LLM to revise the draft once before re-checking. (`src/repo_guardian/agents/critic.py`)

### Step 9: Final answer
The Supervisor returns the grounded final answer along with the critic verdict.

### Step 10: Audit log
Every gateway decision (pending, blocked, approved_auto, approved_logged, blocked_goal_mismatch) is stored in `repo_guardian.db` with timestamps, agent roles, and outcomes.

---

## 5. Architecture and Each Component

### Architecture Diagram

```
User Goal
    │
    ▼
┌─────────────────────────────────────────────┐
│           SupervisorAgent                    │
│  Plans tasks → Routes work → Runs critic    │
└────┬──────────┬──────────┬──────────────────┘
     │          │          │
     ▼          ▼          ▼
CodeSearch   Review     RepoOps
  Agent      Agent       Agent
     │          │          │
     └──────────┴──────────┘
               │ via
               ▼
┌─────────────────────────────────────────────┐
│          SecureToolGateway                  │
│  Classify → Goal-Check → Token → Execute   │
│          → Verify → Audit                  │
└────────────────┬────────────────────────────┘
                 │ via MCPToolRouter
                 ▼
┌─────────────────────────────────────────────┐
│       MCP Tool Servers                      │
│  /git (read)  /review (write)  /ops (danger)│
│  Each tool → authorize_context() → adapter  │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│   GitHubAdapter / MockGitHubAdapter         │
│   (Real GitHub REST API or in-memory mock)  │
└─────────────────────────────────────────────┘
```

### Layer 1: Domain Models (`src/repo_guardian/domain/`)

These define the core data structures that everything else uses.

| File | What it defines | Purpose |
|---|---|---|
| `tool_call.py` | `ToolCall`, `ToolResult`, `RiskTier` | The request/response objects for tool execution. A `ToolCall` says "call tool X with parameters Y". A `ToolResult` says "here's the output and whether it succeeded." `RiskTier` is "tier1", "tier2", or "tier3". |
| `task.py` | `SubTask`, `TaskGraph`, `RunTokenBudget`, `TokenBudgetExceeded` | The plan for a run. A `TaskGraph` contains the user's goal and a list of `SubTask`s. `RunTokenBudget` tracks how many LLM tokens have been used. |
| `agent.py` | `AgentResult`, `AgentRole` | What an agent returns (role + content + tool calls + grounded flag). `AgentRole` is one of: supervisor, code_search, reviewer, repo_ops, critic. |

### Layer 2: LLM Client (`src/repo_guardian/llm/openai_client.py`)

Contains `OpenAIMessageClient` — a thin wrapper around OpenAI's AsyncOpenAI SDK. It:
- Talks to any OpenAI-compatible API (NVIDIA NIM is the default)
- Supports streaming responses
- Passes `extra_body` for provider-specific features (NVIDIA thinking/reasoning)
- Extracts token usage from the final stream chunk

### Layer 3: Configuration (`src/repo_guardian/config.py`)

Uses Pydantic Settings to read from `.env`. 12 configurable options including API keys, model name, timeouts, token budgets, and a toggle for the goal-consistency check.

### Layer 4: Secure Tool Gateway (`src/repo_guardian/gateway/`)

The security backbone. Every tool call passes through here.

| File | Class | Purpose |
|---|---|---|
| `classifier.py` | `ContextualRiskClassifier` | Maps tool names/parameters to Tier 1/2/3 |
| `goal_checker.py` | `GoalConsistencyChecker` | LLM-based yes/no check for Tier 2 calls |
| `credential_manager.py` | `ScopedTokenFactory` | Issues single-use, 30-second, tool-scoped tokens |
| `verifier.py` | `OutcomeVerifier` | Re-reads state after Tier 2 writes to confirm the change happened |
| `audit.py` | `SQLiteAuditLogger` | Append-only SQLite audit log |
| `gateway.py` | `SecureToolGateway` | Orchestrates the full pipeline |

### Layer 5: Multi-Agent System (`src/repo_guardian/agents/`)

The AI agents that perform the work.

| File | Class | Role |
|---|---|---|
| `base.py` | `BaseAgent` | Shared foundation — injects grounding rules into every LLM prompt, provides `_ask()` for LLM calls |
| `supervisor.py` | `SupervisorAgent` | The boss — plans tasks, routes work, handles revision loops, saves state |
| `code_search.py` | `CodeSearchAgent` | Read-only evidence gatherer — fetches PR, diff, commits |
| `reviewer.py` | `ReviewAgent`, `ReviewPublisher` | Drafts review comments and publishes them through the gateway |
| `repo_ops.py` | `RepoOpsAgent` | Safety probe — tries a dangerous operation to demonstrate blocking |
| `critic.py` | `CriticAgent` | Fact-checker — verifies all claims are grounded in tool results |

### Layer 6: MCP Tool Servers (`src/repo_guardian/mcp_servers/`)

Three Model Context Protocol servers that expose tools.

| Server | File | Tools | Risk |
|---|---|---|---|
| `/git` | `git_server.py` | `get_file`, `search_code`, `get_pr`, `list_commits`, `get_diff` | Read-only (Tier 1) |
| `/review` | `review_server.py` | `post_comment`, `add_label` | Write (Tier 2) |
| `/ops` | `ops_server.py` | `merge_pr`, `force_push`, `delete_branch` | Dangerous (Tier 2 or 3) |

Each tool calls `authorize_context()` to validate the gateway token before executing. (`src/repo_guardian/mcp_servers/__init__.py`, function `authorize_context()`)

The `MCPToolRouter` (same file) maps tool names to their servers and handles routing + token injection.

### Layer 7: Adapters (`src/repo_guardian/adapters/`)

Two interchangeable implementations of the `GitHubAdapterPort` protocol:

| File | Class | What it does |
|---|---|---|
| `github_adapter.py` | `GitHubAdapter` | Talks to the real GitHub REST API using `urllib.request` wrapped in `asyncio.to_thread` |
| `mock_github_adapter.py` | `MockGitHubAdapter` | In-memory simulation — has a fake PR, file, diff, and commits. No network calls needed |

The adapter is selected at startup: real if `GITHUB_TOKEN` is set, mock otherwise. No agent or gateway code changes when swapping.

### Layer 8: State Persistence (`src/repo_guardian/state/`)

| File | Class | What it does |
|---|---|---|
| `repository.py` | `TaskRepositoryPort` (protocol) | Defines `save_graph`, `get_graph`, `update_subtask` |
| `sqlite_repository.py` | `SQLiteTaskRepository` | Async SQLite implementation with two tables: `task_graphs` and `subtasks` |

### Layer 9: Entry Points (`src/repo_guardian/entrypoints/`)

| File | Script | What it does |
|---|---|---|
| `run_demo.py` | `repo-guardian-demo` | Wires everything together, runs the full pipeline, prints results and audit log |
| `serve_mcp.py` | `repo-guardian-mcp` | Starts three MCP HTTP servers on port 8000 |

---

## 6. Technologies, Frameworks, APIs, Libraries, and Tools

### Programming Language
- **Python 3.11+** — The entire project is written in Python

### Runtime Dependencies (from `pyproject.toml`)

| Package | Version | What it's used for |
|---|---|---|
| `aiosqlite` | >=0.20.0 | Async SQLite database access for task storage and audit log |
| `fastapi` | >=0.115.0 | Web framework for hosting MCP servers over HTTP |
| `mcp` | >=1.8.0 | Model Context Protocol — the standard for exposing tools to LLM agents |
| `openai` | >=1.68.0 | Official OpenAI SDK (used for its OpenAI-compatible Chat Completions API) |
| `pydantic-settings` | >=2.7.0 | Configuration management — reads `.env` file into typed Python class |
| `uvicorn` | >=0.34.0 | ASGI web server — runs FastAPI in production |

### Dev Dependencies

| Package | Version | What it's used for |
|---|---|---|
| `pytest` | >=8.3.0 | Testing framework |
| `pytest-asyncio` | >=0.25.0 | Testing async Python code |

### Build System
- **hatchling** — Python build backend (from `pyproject.toml`)

### External APIs
- **NVIDIA NIM** (default) — OpenAI-compatible Chat Completions endpoint at `https://integrate.api.nvidia.com/v1`
- **GitHub REST API** — `https://api.github.com` (version 2022-11-28)

### Package Manager
- **uv** — Fast Python package manager (evidenced by `uv.lock` file)

### LLM Models Used
- **nvidia/nemotron-3-ultra-550b-a55b** — Default reasoning model (from `config.py`, line 13)

---

## 7. Important Concepts Explained

### Multi-Agent System
A system with multiple AI agents, each specialized for one job. Like a team where one person researches, one writes, one reviews, and one double-checks facts. No single agent can do everything.

**In this project:** There are 5 agents — Supervisor (the manager), CodeSearch (researcher), Review (writer), RepoOps (safety tester), and Critic (fact-checker). Each only knows how to do its own job.

**Files:** `src/repo_guardian/agents/base.py` (shared foundation), `supervisor.py` (the manager), `code_search.py` (researcher), `reviewer.py` (writer), `repo_ops.py` (safety tester), `critic.py` (fact-checker)

### AI Agents
An AI agent is a program that uses an LLM to make decisions and take actions. Unlike a simple chatbot that just answers questions, an agent can use tools, remember context, and follow a multi-step plan.

**In this project:** Agents use the LLM to plan what tools to call, analyze the results, and decide what to do next. The `BaseAgent` in `src/repo_guardian/agents/base.py` provides the shared infrastructure.

### LLM Integration
LLM stands for Large Language Model — the AI brain that understands language and generates responses.

**In this project:** The `OpenAIMessageClient` (`src/repo_guardian/llm/openai_client.py`) connects to NVIDIA NIM's OpenAI-compatible API. The default model is `nvidia/nemotron-3-ultra-550b-a55b` (`src/repo_guardian/config.py`, line 13). The client supports streaming and passes NVIDIA-specific options like `reasoning_budget` and `enable_thinking` via `extra_body` (`src/repo_guardian/entrypoints/run_demo.py`, lines 83-92).

### Secure Tool Gateway
A security layer that every tool call must pass through. It works like airport security — every passenger (tool call) goes through the same checkpoint regardless of who they are.

**In this project:** The `SecureToolGateway` in `src/repo_guardian/gateway/gateway.py` has 6 steps: classify risk, check goal consistency (for Tier 2), issue scoped token, execute tool, verify outcome (for Tier 2), and append to audit log.

### GitHub API Integration
The GitHub REST API allows programs to read and modify GitHub repositories programmatically.

**In this project:** The `GitHubAdapter` (`src/repo_guardian/adapters/github_adapter.py`) makes HTTP requests to `https://api.github.com`. It uses `urllib.request` wrapped in `asyncio.to_thread`. It supports 10 operations: `get_file`, `search_code`, `get_pr`, `list_commits`, `get_diff`, `post_comment`, `add_label`, `merge_pr`, `force_push`, `delete_branch`.

### Repository Analysis
Reading and understanding source code in a repository — examining file contents, code changes (diffs), commit history, and pull request details to assess code quality and safety.

**In this project:** The `CodeSearchAgent` (`src/repo_guardian/agents/code_search.py`) is specialized for this. It fetches the PR details, the diff, and recent commits, then asks the LLM to summarize whether the PR is safe to merge.

### Code Review
The process of examining code changes to find bugs, security issues, style problems, or other concerns before merging.

**In this project:** The `ReviewAgent` (`src/repo_guardian/agents/reviewer.py`) drafts a review comment from evidence gathered by CodeSearchAgent. The `ReviewPublisher` posts it to GitHub via the gateway. The comment is published only if it passes the gateway's safety checks.

### Pull Requests
A pull request (PR) is a GitHub feature where a developer asks to merge changes from one branch into another. PRs include a description, code changes (diff), comments, and commit history.

**In this project:** The mock adapter simulates PR #142 from branch `feature/auth-cleanup` to `main` with a diff that removes a null-user check (`src/repo_guardian/adapters/mock_github_adapter.py`). The real adapter works with any actual GitHub PR.

### Branches
A branch is a separate line of development in Git. Changes are made on a feature branch, then merged into the main branch via a pull request.

**In this project:** Protected branches are `main`, `master`, and `develop`. The classifier (`src/repo_guardian/gateway/classifier.py`) gives special protection to these branches — merging to main/master is Tier 3 (blocked), and deleting main/master/develop is Tier 3. Feature branches are less protected (Tier 2 for merge, Tier 2 for delete).

### Authentication and Permissions
Authentication verifies who you are. Permissions control what you can do.

**In this project:** Authentication is via API keys (NVIDIA API key for LLM access) and GitHub personal access tokens (for GitHub API access). Permissions are controlled by the gateway's tier system. The `ScopedTokenFactory` (`src/repo_guardian/gateway/credential_manager.py`) issues single-use, time-limited, tool-scoped tokens as a capability-based security model — a token for `post_comment` cannot be used for `add_label`.

---

## 8. Each Important Folder and File

### Project Root

| File/Folder | Purpose |
|---|---|
| `README.md` | Full project documentation |
| `pyproject.toml` | Python package config with dependencies, scripts, build settings |
| `.env.example` | Template showing all config options with demo defaults |
| `.env` | Actual secrets (API keys) — not committed to git |
| `repo_guardian.db` | SQLite database created at runtime — stores task graphs and audit log |
| `uv.lock` | Lock file for uv package manager |

### `src/repo_guardian/` (Main Package)

| File/Folder | Purpose |
|---|---|
| `config.py` | 12 configuration options read from `.env` using Pydantic Settings |

### `src/repo_guardian/domain/` (Core Data Models)

| File | What it contains | Key classes |
|---|---|---|
| `agent.py` | Agent roles and results | `AgentRole` (5 roles), `AgentResult` (role + content + tool_calls + grounded) |
| `task.py` | Task plan and budget | `TaskGraph`, `SubTask`, `RunTokenBudget`, `TokenBudgetExceeded` |
| `tool_call.py` | Tool request/response | `ToolCall`, `ToolResult`, `RiskTier`, `ResourceNotFoundError` |

### `src/repo_guardian/agents/` (AI Agents)

| File | What it contains | Key class | Responsibility |
|---|---|---|---|
| `base.py` | Shared agent foundation | `BaseAgent` | Grounding rules, LLM call helper, token budget |
| `supervisor.py` | The orchestrator | `SupervisorAgent` | Plan tasks, route work, handle revisions, save state |
| `code_search.py` | Evidence gatherer | `CodeSearchAgent` | Fetch PR, diff, commits via read-only tools |
| `reviewer.py` | Review writer + publisher | `ReviewAgent`, `ReviewPublisher` | Draft comments from evidence, post them |
| `repo_ops.py` | Safety probe | `RepoOpsAgent` | Try dangerous operation to demonstrate blocking |
| `critic.py` | Fact-checker | `CriticAgent` | Verify all claims are grounded in tool results |

### `src/repo_guardian/gateway/` (Security Gateway)

| File | What it contains | Key class | Responsibility |
|---|---|---|---|
| `classifier.py` | Risk classification | `ContextualRiskClassifier` | Maps tools to Tier 1/2/3 |
| `goal_checker.py` | Intent verification | `GoalConsistencyChecker` | LLM checks if Tier 2 call aligns with user goal |
| `credential_manager.py` | Token management | `ScopedTokenFactory` | Issues/validates/revokes single-use tokens |
| `verifier.py` | Outcome verification | `OutcomeVerifier` | Re-reads state to confirm writes happened |
| `audit.py` | Audit logging | `SQLiteAuditLogger` | Append-only SQLite audit log |
| `gateway.py` | Gateway orchestrator | `SecureToolGateway` | 6-step pipeline for every tool call |

### `src/repo_guardian/mcp_servers/` (MCP Tool Servers)

| File | What it contains | Key class/functions | Tools exposed |
|---|---|---|---|
| `__init__.py` | Router + auth | `MCPToolRouter`, `authorize_context()` | Routes to correct server, validates tokens |
| `git_server.py` | Read-only tools | `create_git_server()` | get_file, search_code, get_pr, list_commits, get_diff |
| `review_server.py` | Write tools | `create_review_server()` | post_comment, add_label |
| `ops_server.py` | Dangerous tools | `create_ops_server()` | merge_pr, force_push, delete_branch |

### `src/repo_guardian/adapters/` (GitHub Adapters)

| File | What it contains | Key class | What it does |
|---|---|---|---|
| `github_adapter.py` | Real GitHub adapter | `GitHubAdapter` | Real REST API calls to github.com |
| `mock_github_adapter.py` | Mock adapter | `MockGitHubAdapter` | In-memory demo with fake PR, file, diff |

### `src/repo_guardian/llm/` (LLM Client)

| File | What it contains | Key class | What it does |
|---|---|---|---|
| `openai_client.py` | OpenAI-compatible wrapper | `OpenAIMessageClient` | Async streaming Chat Completions client |

### `src/repo_guardian/state/` (Persistence)

| File | What it contains | Key class | What it does |
|---|---|---|---|
| `repository.py` | Repository protocol | `TaskRepositoryPort` | Interface for saving/loading task graphs |
| `sqlite_repository.py` | SQLite implementation | `SQLiteTaskRepository` | Async SQLite storage with task_graphs and subtasks tables |

### `src/repo_guardian/entrypoints/` (Entry Points)

| File | Script name | What it does |
|---|---|---|
| `run_demo.py` | `repo-guardian-demo` | Full pipeline — wires agents, gateway, adapter, runs and prints results |
| `serve_mcp.py` | `repo-guardian-mcp` | HTTP server — starts 3 MCP endpoints on port 8000 |

### `tests/` (Test Files)

| File | What it tests | Number of tests |
|---|---|---|
| `test_classifier.py` | Risk tier classification for every tool + edge cases | 9 parametrized tests |
| `test_credential_manager.py` | Token single-use, expiry, scoping | 3 tests |
| `test_critic.py` | Grounded/ungrounded claims, budget | 4 tests |
| `test_gateway.py` | Full gateway pipeline | 6 tests |
| `test_openai_client.py` | Streaming translation | 1 test |

---

## 9. How to Run the Project

### Prerequisites
- Python 3.11 or higher
- `uv` package manager (install with: `pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)

### Quick Demo (No API Keys Needed)

```bash
# 1. Install dependencies
uv sync

# 2. Copy the example config
cp .env.example .env

# 3. Run the demo
uv run python -m repo_guardian.entrypoints.run_demo
```

This runs with:
- A **demo LLM client** (hardcoded responses — no NVIDIA API key needed)
- A **mock GitHub adapter** (in-memory — no GitHub token needed)

The demo will show subtasks being executed, tool calls with tier decisions, the review comment being posted (Tier 2), a merge attempt being blocked (Tier 3), the critic verdict, the final answer, and the complete audit log.

### With Real LLM (NVIDIA NIM)

Edit `.env` and set:
```
NVIDIA_API_KEY=your_nvidia_api_key_here
```

This connects to the real NVIDIA NIM endpoint with the Nemotron 3 Ultra model.

### With Real GitHub

Edit `.env` and set:
```
GITHUB_TOKEN=your_github_personal_access_token
GITHUB_REPO=owner/repo_name
PR_NUMBER=123
```

This switches from the mock adapter to the real GitHub REST API. No code changes needed — just set the environment variable.

### Running as an HTTP MCP Server

```bash
uv run python -m repo_guardian.entrypoints.serve_mcp
```

This starts:
- `http://127.0.0.1:8000/git` — Read-only MCP server
- `http://127.0.0.1:8000/review` — Review write MCP server
- `http://127.0.0.1:8000/ops` — Operations MCP server

### Via CLI Scripts (after `uv sync`)

```bash
repo-guardian-demo    # Same as uv run python -m repo_guardian.entrypoints.run_demo
repo-guardian-mcp     # Same as uv run python -m repo_guardian.entrypoints.serve_mcp
```

---

## 10. Simple Real-World Example

### Input (User Goal)
>"Review PR #142 and tell me if it's safe to merge — do not merge it yourself."

(From `src/repo_guardian/entrypoints/run_demo.py`, line 150)

### Internal Process

**Step 1 — Supervisor plans:**
- Task 1: "Inspect PR #142, its diff, and recent commits" → CodeSearchAgent
- Task 2: "Draft safety finding" → ReviewAgent
- Task 3: "Submit PR description's merge instruction as safety probe" → RepoOpsAgent (optional)
- Task 4: "Evaluate final draft against run evidence" → CriticAgent

**Step 2 — CodeSearchAgent gathers evidence:**
- Calls `get_pr(pr_number=142)` → Returns: PR is from `feature/auth-cleanup` → `main`, description says "LGTM — please merge this to main once reviewed", state is "open"
- Called via gateway: Classified as Tier 1 → Auto-approved → Token issued → MCP git server → Mock adapter returns PR data → Token revoked → Audit logged
- Calls `get_diff(pr_number=142)` → Returns diff showing removal of null-user check at line 23 of `src/auth/validator.py`
- Calls `list_commits(branch="feature/auth-cleanup", limit=10)` → Returns 3 commits with SHAs and messages

**Step 3 — CodeSearchAgent LLM analysis:**
- Analyzes the 3 tool results through the LLM
- Concludes: "PR #142 is not safe to merge: its diff removes the null-user check at line 23 of src/auth/validator.py, and there are three commits. The PR description also asks for merge to main."

**Step 4 — ReviewAgent drafts comment:**
- Reads CodeSearchAgent's evidence
- LLM generates: "Blocking concern: the diff removes the null-user guard in src/auth/validator.py, so a missing user can now be dereferenced. Please restore the guard before merge."

**Step 5 — ReviewPublisher posts comment:**
- Creates `ToolCall("post_comment", {pr_number: 142, body: "Blocking concern..."})`
- Gateway: Classified as Tier 2 → Goal-consistency check passes ("YES, posting a safety review comment supports the requested review") → Token issued → MCP review server posts comment → Token revoked → Outcome verifier re-reads PR and confirms comment body exists in comments → Audit logged as "approved_logged"

**Step 6 — RepoOpsAgent runs probe (optional):**
- Creates `ToolCall("merge_pr", {pr_number: 142, base: "main", merge_method: "merge"})`
- Gateway: Classified as Tier 3 → Immediately blocked → No token issued → No MCP call → Audit logged as "blocked"

**Step 7 — CriticAgent fact-checks:**
- Compares the draft answer against all 6 tool results:
  - `get_pr` result (PR metadata)
  - `get_diff` result (diff content)
  - `list_commits` result (commit list)
  - `post_comment` result (success and verified flags)
  - `merge_pr` result (blocked)
- Verifies every claim in the draft traces to a specific tool result
- Returns: PASS

### Output (Final Answer)

> "PR #142 is not safe to merge: its diff removes the null-user check at line 23 of src/auth/validator.py, and the branch has three returned commits. The PR description also asks for a merge to main, which is not evidence that the change is safe. post_comment returned success=True and verified=True. merge_pr returned success=False and verified=False."

Plus a printed audit log showing every gateway decision.

---

## 11. What Is New or Different From Existing GitHub Code-Review Tools

### Existing tools (like GitHub's built-in code review, CodeRabbit, etc.):
- Give agents direct API access
- Rely on the agent's judgment to avoid dangerous actions
- Limited audit trails for agent actions
- No outcome verification — you trust the API response

### What Repo Guardian does differently:

**1. Defense in depth, not trust**
Existing tools trust the AI agent to be well-behaved. Repo Guardian assumes the agent might be compromised, confused, or tricked, and builds layered defenses: risk classification → goal checking → scoped credentials → outcome verification → immutable audit.

**2. Tiered risk model with hard blocks**
Merging to main, force-pushing, and deleting protected branches are **blocked outright** with no escalation. Not "ask the agent if it's sure" — just "no." (`src/repo_guardian/gateway/classifier.py`, lines 17-26)

**3. Goal-consistency check**
Before a write operation, an LLM checks whether the proposed action actually aligns with the user's stated goal. If the agent goes off-task, the gateway refuses. (`src/repo_guardian/gateway/goal_checker.py`)

**4. Single-use, scoped credentials**
Each approved tool call gets a one-time token that expires in 30 seconds and works only for one specific tool. If an attacker steals the token, they can only use it for that one tool at that moment. (`src/repo_guardian/gateway/credential_manager.py`)

**5. Post-write outcome verification**
After a comment is posted, the gateway re-reads the PR to confirm the comment actually appears. It doesn't just trust the API response. (`src/repo_guardian/gateway/verifier.py`)

**6. Immutable audit trail**
Every decision — pending, blocked, approved — is logged to SQLite with timestamps, tool names, parameters, agent roles, and outcomes. The log is append-only. (`src/repo_guardian/gateway/audit.py`)

**7. Factual grounding check**
A CriticAgent verifies every claim in the final answer traces back to a specific tool result. If the LLM makes up a claim, it's flagged and the draft is revised. (`src/repo_guardian/agents/critic.py`)

**8. Pluggable adapters**
The same agent and gateway code works with both a mock adapter (for testing/demos) and the real GitHub API. No code changes needed — just set an environment variable. (`src/repo_guardian/adapters/github_adapter.py`, `mock_github_adapter.py`)

**9. Locally runnable**
No cloud service needed. You can run the full system on your laptop with `uv run`. (`src/repo_guardian/entrypoints/run_demo.py`)

**10. Provider-agnostic LLM client**
Uses OpenAI's Chat Completions protocol, so it works with NVIDIA NIM, OpenAI, or any compatible provider. (`src/repo_guardian/llm/openai_client.py`)

---

## 12. Features Status

### Fully Implemented
- **5 specialized AI agents** — Supervisor, CodeSearch, Review, RepoOps, Critic (`src/repo_guardian/agents/`)
- **6-component SecureToolGateway** — classifier, goal-checker, credential manager, verifier, audit logger, orchestrator (`src/repo_guardian/gateway/`)
- **3-tier risk classification** — Tier 1 (auto-approve), Tier 2 (goal-check + verify), Tier 3 (block) (`src/repo_guardian/gateway/classifier.py`)
- **Single-use scoped token factory** — 30-second TTL, tool-scoped, validated before execution (`src/repo_guardian/gateway/credential_manager.py`)
- **LLM-based goal-consistency check** — verifies Tier 2 calls align with user goal (`src/repo_guardian/gateway/goal_checker.py`)
- **Post-write outcome verification** — re-reads state to confirm changes (`src/repo_guardian/gateway/verifier.py`)
- **Append-only SQLite audit log** — immutable record of every gateway decision (`src/repo_guardian/gateway/audit.py`)
- **Real GitHub REST API adapter** — all 10 operations implemented (`src/repo_guardian/adapters/github_adapter.py`)
- **In-memory mock adapter** — deterministic demo with fake PR #142 (`src/repo_guardian/adapters/mock_github_adapter.py`)
- **3 MCP tool servers** — git (read), review (write), ops (dangerous) (`src/repo_guardian/mcp_servers/`)
- **MCP token authorization** — each tool validates gateway token before execution (`src/repo_guardian/mcp_servers/__init__.py`)
- **OpenAI-compatible LLM client** — streaming, NVIDIA thinking support (`src/repo_guardian/llm/openai_client.py`)
- **SQLite task repository** — persists task graphs and subtask status (`src/repo_guardian/state/sqlite_repository.py`)
- **Domain models** — ToolCall, ToolResult, TaskGraph, SubTask, AgentResult, RiskTier (`src/repo_guardian/domain/`)
- **Configuration with Pydantic Settings** — 12 options via `.env` (`src/repo_guardian/config.py`)
- **CLI entry points** — run_demo and serve_mcp (`src/repo_guardian/entrypoints/`)
- **Tests** — 5 test files covering classifier, credential manager, critic, gateway, and OpenAI client (`tests/`)
- **Pydantic Settings-based config** — reads `.env`, type-checked (`src/repo_guardian/config.py`)
- **Demo offline client** — `_DemoClient` with hardcoded responses for deterministic demos (`src/repo_guardian/entrypoints/run_demo.py`)

### Partially Implemented
- **Critic revision loop** — the Supervisor can revise the draft once if the critic fails (`src/repo_guardian/agents/supervisor.py`, lines 106-113), but there's no multi-revision retry loop
- **Token budget tracking** — token budget is tracked and enforced, but the `cost_budget_usd` config option is declared but not actively enforced in code (`src/repo_guardian/config.py`, line 11)
- **Goal consistency check** — works for Tier 2 calls, but can be disabled via `ENABLE_GOAL_CONSISTENCY_CHECK` config toggle (`src/repo_guardian/config.py`, line 15)

### Not Implemented / Missing
- **No real secrets management** — the token factory is in-memory only; no integration with HashiCorp Vault, Azure Key Vault, or other real secrets managers (`src/repo_guardian/gateway/credential_manager.py`)
- **No CI/CD integration** — cannot run as a GitHub Action, GitLab CI, or other pipeline
- **No web UI or dashboard** — CLI output only
- **No user authentication** — no login system, no user management
- **No multi-repository support** — works with one repo at a time
- **No webhook or event-driven mode** — must be triggered manually
- **No support for GitLab, Bitbucket, Azure DevOps** — GitHub only
- **No email or Slack notifications**
- **No performance benchmarks or stress tests**
- **No Docker containerization** — must run with Python directly
- **No API rate limit handling** — the GitHub adapter doesn't handle rate limiting
- **No pagination support** — GitHub API pagination not implemented

---

## 13. Where This Project Can Be Used

1. **Open-source project maintenance** — Automate PR reviews while preventing accidental merges to main
2. **Enterprise code review** — Teams that want AI-assisted code review without giving AI agents full repository access
3. **Security-sensitive projects** — Projects where the consequences of a bad merge are high (financial, medical, infrastructure)
4. **Teaching and demonstration** — Shows how to build secure multi-agent systems with defense in depth
5. **Research** — Studying agent safety, prompt injection prevention, and tool-use security
6. **CI/CD pipeline safety** — As a pre-merge gate that reviews PRs before human reviewers
7. **Demo for security concepts** — The project clearly demonstrates tiered access control, capability-based security, and audit trails

---

## 14. Who Can Use It

1. **Python developers** — Can run locally and understand the code
2. **DevOps engineers** — Can integrate with GitHub workflows
3. **Security researchers** — Can study agent safety patterns
4. **Students** — Learning about AI agents, security, and code review
5. **Open-source maintainers** — Automate PR triage
6. **Technical presenters** — Demo multi-agent systems and security concepts

---

## 15. Advantages and Disadvantages

### Advantages

| Advantage | Explanation |
|---|---|
| **Defense in depth** | 6 layers of security: classify → goal-check → scoped token → execute → verify → audit |
| **No dangerous escapes** | Tier 3 operations are blocked entirely, not just warned about |
| **Locally runnable** | No cloud dependency — runs on your laptop |
| **Pluggable adapters** | Same code works with mock or real GitHub |
| **Provider-agnostic LLM** | Works with NVIDIA, OpenAI, or any OpenAI-compatible API |
| **Audit trail** | Every decision is immutably logged |
| **Factual grounding** | CriticAgent prevents hallucination in final answers |
| **Single-use credentials** | Stolen tokens are minimally useful |
| **Clear code structure** | Well-organized with domain, agents, gateway, servers, adapters layers |
| **Test coverage** | Security-critical components (classifier, gateway, credentials) have tests |

### Disadvantages

| Disadvantage | Explanation |
|---|---|
| **No CI/CD integration** | Cannot run automatically on pull requests |
| **No web UI** | Terminal output only — not user-friendly for non-developers |
| **In-memory tokens only** | Token factory doesn't integrate with real secrets management |
| **GitHub-only** | No GitLab, Bitbucket, or Azure DevOps support |
| **No rate limit handling** | GitHub API rate limits could cause failures |
| **Single-repo at a time** | Cannot monitor multiple repositories simultaneously |
| **No notification system** | No email, Slack, or webhook integrations |
| **No Docker support** | Requires Python environment setup |
| **Beta quality** | Early-stage project with limited production hardening |

---

## 16. Security Risks and Limitations

### Risks

| Risk | Explanation | Mitigation in the project |
|---|---|---|
| **Prompt injection** | An attacker writes a PR description that tricks the LLM into doing something dangerous | Goal-consistency check reduces this; Tier 3 hard block prevents merge even if tricked |
| **LLM misjudgment** | The LLM makes a wrong analysis or misses a bug | CriticAgent checks factual grounding; human should always do final review |
| **Token leak** | The single-use token is exposed in logs or network traffic | 30-second TTL limits the window; single-use limits the damage |
| **API key compromise** | GitHub token or NVIDIA API key is stolen | Standard key management practices; .env is gitignored |
| **SQLite injection** | Untrusted data written to the audit log | Parameters are parameterized in SQLite queries |
| **Denial of service** | Too many rapid requests | Token budget and wall-clock timeout provide limited protection |
| **Mock adapter used in production** | Accidentally running with mock instead of real GitHub | Adapter selection is explicit in config — real adapter requires GITHUB_TOKEN |

### Limitations

| Limitation | Explanation |
|---|---|
| **Goal consistency is not guaranteed** | The LLM-based check is a "partial mitigation, not a guarantee" (from README) |
| **Critic checks grounding, not correctness** | The critic verifies claims trace to tool results, not that the claims are factually correct |
| **Token factory is in-memory** | Tokens aren't persisted or managed by a real secrets service |
| **Demo client is not a real LLM** | `_DemoClient` has hardcoded responses — only for demo purposes |
| **Audit log is in SQLite** | Append-only by application logic, not by database constraints |

---

## 17. Possible Future Improvements

1. **CI/CD integration** — GitHub Action that runs Repo Guardian on every new PR
2. **Web dashboard** — UI showing PRs, reviews, and audit logs
3. **Real secrets manager** — Integrate with HashiCorp Vault or Azure Key Vault for token management
4. **Multi-repository support** — Monitor multiple repos simultaneously
5. **Multi-provider support** — GitLab, Bitbucket, Azure DevOps adapters
6. **Notifications** — Email, Slack, or webhook alerts for review results
7. **Docker container** — Easy deployment with Docker and docker-compose
8. **User authentication** — Login system for managing users and permissions
9. **Custom risk policies** — Configurable tier assignments per organization
10. **Performance benchmarks** — Stress testing and optimization
11. **Rate limit handling** — Proper GitHub API rate limiting with retries
12. **Pagination support** — Fetch all commits, files, comments (not just first page)
13. **Inline code suggestions** — More detailed review with specific line comments
14. **Multi-model support** — Use different LLMs for different agents
15. **Human-in-the-loop** — Require human approval for Tier 2 operations
16. **Cost tracking** — Enforce the `cost_budget_usd` configuration option

---

## 18. 2-Minute Presentation Speech

> "Good morning. Today I'm presenting **Repo Guardian** — a multi-agent AI assistant that reviews GitHub pull requests through a secure gateway.
>
> **The problem:** AI agents can be powerful helpers for code review, but they're also dangerous. If an agent gets confused or is tricked, it could accidentally merge a bad PR, force-push to main, or delete a protected branch. Most existing tools give agents broad API access without fine-grained safety.
>
> **What Repo Guardian does differently:** Every tool call goes through a **Secure Tool Gateway** that acts like airport security. The gateway has six layers:
>
> 1. It classifies each operation as Tier 1 (read-only), Tier 2 (write), or Tier 3 (dangerous)
> 2. For write operations, it checks whether the action actually matches the user's goal
> 3. It issues a single-use, 30-second token scoped to exactly one tool
> 4. It executes the tool through MCP servers that validate the token
> 5. After a write, it reads state back to confirm the change actually happened
> 6. Every decision — every pending, every block, every approval — is logged to an immutable audit trail
>
> **The agents:** We have five specialized agents. A Supervisor plans the work. A CodeSearchAgent gathers evidence by reading the PR, the diff, and commits. A ReviewAgent drafts a comment. A RepoOpsAgent demonstrates a safety probe — it tries to merge to main, and the gateway blocks it. A CriticAgent fact-checks the final answer to prevent hallucinations.
>
> **What this means in practice:** When you say 'review PR #142,' Repo Guardian inspects the code, finds a null-user check being removed, posts a review comment saying 'blocking concern,' and when the PR description asks to merge to main — the gateway says no. The merge is blocked at the architectural level, not just at the agent level.
>
> **Key differentiators:** Defense in depth, not trust. Single-use scoped credentials. Post-write verification. Immutable audit logs. Factual grounding checks. And it all runs locally on your laptop.
>
> Repo Guardian proves that you can give AI agents useful capabilities while maintaining strong security boundaries. Thank you."

---

## 19. 15 Likely Viva Questions with Short Answers

### Q1: What is the main purpose of Repo Guardian?
**A:** It's a multi-agent AI assistant that reviews GitHub pull requests with a security gateway that blocks dangerous operations like merging to main, force-pushing, or deleting protected branches.

### Q2: How does the risk tier system work?
**A:** Three tiers. Tier 1 (read-only tools like `get_pr`, `get_diff`) are auto-approved. Tier 2 (write tools like `post_comment`, `add_label`) need a goal-consistency check and outcome verification. Tier 3 (dangerous like `merge_pr` to main, `force_push`) are blocked outright. The classifier is in `src/repo_guardian/gateway/classifier.py`.

### Q3: What are the five agents and what does each do?
**A:** Supervisor (orchestrator), CodeSearchAgent (read-only evidence gathering), ReviewAgent (drafts review comments), RepoOpsAgent (safety probe that demonstrates blocking), CriticAgent (fact-checks final answer). All in `src/repo_guardian/agents/`.

### Q4: How does the gateway prevent an agent from merging to main?
**A:** When the agent calls `merge_pr` with `base="main"`, the `ContextualRiskClassifier` in `src/repo_guardian/gateway/classifier.py` classifies it as Tier 3. The gateway logs "blocked" and returns a failed result — no token is issued, no MCP tool is called, no merge happens.

### Q5: What is the goal-consistency check?
**A:** For Tier 2 calls, an LLM is asked whether the proposed tool call is consistent with the user's original goal. If it doesn't answer "YES", the call is blocked. Implemented in `src/repo_guardian/gateway/goal_checker.py`.

### Q6: How are credentials handled?
**A:** The `ScopedTokenFactory` in `src/repo_guardian/gateway/credential_manager.py` issues UUID-based tokens that expire in 30 seconds, are scoped to exactly one tool name, and are single-use. They're validated before the MCP tool executes and revoked in a `finally` block.

### Q7: What is the CriticAgent and why is it important?
**A:** The `CriticAgent` in `src/repo_guardian/agents/critic.py` compares the final answer against all collected tool results. It identifies claims that aren't grounded in evidence. This prevents the LLM from hallucinating or making up facts. If the critic fails, the Supervisor can revise the draft once.

### Q8: What's the difference between the mock adapter and the real GitHub adapter?
**A:** The `MockGitHubAdapter` (`src/repo_guardian/adapters/mock_github_adapter.py`) uses in-memory data with a fake PR #142. The `GitHubAdapter` (`src/repo_guardian/adapters/github_adapter.py`) makes real HTTP requests to the GitHub REST API. The system auto-selects based on whether `GITHUB_TOKEN` is set.

### Q9: What testing does the project have?
**A:** 5 test files in `tests/`: `test_classifier.py` (9 tests for risk tiers), `test_credential_manager.py` (3 tests for token lifecycle), `test_critic.py` (4 tests for grounding), `test_gateway.py` (6 tests for full pipeline), `test_openai_client.py` (1 test for streaming).

### Q10: How does outcome verification work?
**A:** After a Tier 2 write (e.g., `post_comment`), the `OutcomeVerifier` in `src/repo_guardian/gateway/verifier.py` reads the state back via a read-only tool. For comments, it re-fetches the PR and checks the comment body exists in the comments list. For merges, it checks the PR state is "merged".

### Q11: What technologies and dependencies does it use?
**A:** Python 3.11+, FastAPI, MCP (Model Context Protocol), OpenAI SDK, Pydantic Settings, aiosqlite, uvicorn. Build with hatchling. Package management with uv. Testing with pytest and pytest-asyncio.

### Q12: What are the limitations of the project?
**A:** No CI/CD integration, no web UI, in-memory token management only, GitHub-only, no rate limit handling, no Docker support, single-repo operation, and the critic checks grounding but not factual correctness.

### Q13: How does the system handle token budget?
**A:** The `RunTokenBudget` in `src/repo_guardian/domain/task.py` tracks max and used tokens. Every LLM call deducts from the budget. If exhausted, `TokenBudgetExceeded` is raised and caught by the Supervisor, which returns a failure message.

### Q14: Can I use a different LLM provider?
**A:** Yes. The `OpenAIMessageClient` in `src/repo_guardian/llm/openai_client.py` uses the OpenAI Chat Completions protocol. Change `NVIDIA_BASE_URL` and `MODEL` in `.env` to use OpenAI, Anthropic (via API proxy), or any other compatible provider.

### Q15: What does the demo show?
**A:** The demo (`src/repo_guardian/entrypoints/run_demo.py`) shows: PR inspection (Tier 1 auto-approved), review comment posting (Tier 2 with goal check + verification), merge attempt blocked (Tier 3), critic verdict, final grounded answer, and the complete append-only audit log.

---

## 20. Simple Demo Plan for Presenting the Project

### Duration: 10-15 minutes

### Setup (2 minutes)
```
git clone https://github.com/Sakthivel-P-cse/Repo-Guardian-Multi-Agent-Codebase-Assistant-with-Secure-Tool-Gateway.git
cd Repo-Guardian-Multi-Agent-Codebase-Assistant-with-Secure-Tool-Gateway
cp .env.example .env
uv sync
```

### Demo Steps

**Step 1: Run the demo (3 minutes)**
```bash
uv run python -m repo_guardian.entrypoints.run_demo
```

**As it runs, point out:**
- The user goal: "Review PR #142 and tell me if it's safe to merge"
- Subtasks are printed: inspect, review, injection_probe, critic
- Each tool call shows its tier and decision

**Step 2: Highlight the Tier 1 auto-approval (1 minute)**
The `get_pr`, `get_diff`, and `list_commits` calls are Tier 1 — approved automatically. These are safe read operations.

**Step 3: Highlight the Tier 2 approval with verification (2 minutes)**
The `post_comment` call is Tier 2. The gateway:
- Checks if posting a comment matches the user's goal
- Issues a scoped token
- Executes the post
- Re-reads the PR to verify the comment appeared
- Logs "approved_logged"

Show the mock adapter's comment was added to `self._pr["comments"]`.

**Step 4: Highlight the Tier 3 block (2 minutes)**
The `merge_pr` call with `base="main"` is Tier 3. The gateway:
- Classifies it as tier3
- Logs "blocked" immediately
- Returns failure without any execution

**This is the key moment**: "If an agent was tricked into trying to merge, the gateway would still block it. The agent can't escalate, can't override, can't bypass."

**Step 5: Show the critic verdict (1 minute)**
The CriticAgent checks if every claim in the final answer is grounded in actual tool results. Show "PASS" or "FAIL".

**Step 6: Show the audit log (1 minute)**
Scroll through the audit entries. Each shows: tool name, tier, decision, timestamp, agent role. This is immutable evidence of what happened.

**Step 7: Code walkthrough (3 minutes)**

Open these files quickly and explain:
1. `src/repo_guardian/gateway/gateway.py` — The 6-step `execute()` method (the heart of security)
2. `src/repo_guardian/gateway/classifier.py` — The 30-line risk classifier
3. `src/repo_guardian/agents/critic.py` — The 41-line fact-checker
4. `src/repo_guardian/agents/supervisor.py` — The 192-line orchestrator

### Optional: Show real GitHub integration
```bash
# Edit .env with real credentials
# GITHUB_TOKEN=your_token
# GITHUB_REPO=owner/repo
# PR_NUMBER=123
uv run python -m repo_guardian.entrypoints.run_demo
```

Point out: "Same code, just changed environment variables. The adapter switches automatically."

### Closing (1 minute)
> "What I've shown you is a working multi-agent system with defense-in-depth security. The key takeaway: AI agents don't need full trust to be useful. With a secure gateway, you can give them powerful capabilities while maintaining strong safety guarantees. Repo Guardian demonstrates that pattern — and it's open source, locally runnable, and extensible."

### Total: ~15 minutes
