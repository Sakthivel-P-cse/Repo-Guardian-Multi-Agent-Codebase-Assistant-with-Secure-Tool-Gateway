import asyncio
from collections.abc import Callable
from uuid import uuid4

from repo_guardian.agents.base import BaseAgent
from repo_guardian.agents.code_search import CodeSearchAgent
from repo_guardian.agents.critic import CriticAgent, CriticResult
from repo_guardian.agents.repo_ops import RepoOpsAgent
from repo_guardian.agents.reviewer import ReviewAgent, ReviewPublisher
from repo_guardian.domain.agent import AgentResult
from repo_guardian.domain.task import SubTask, TaskGraph, TokenBudgetExceeded
from repo_guardian.domain.tool_call import ToolResult
from repo_guardian.state.repository import TaskRepositoryPort


class SupervisorAgent(BaseAgent):
    def __init__(
        self,
        gateway,
        anthropic_client,
        config,
        repository: TaskRepositoryPort,
        code_search_agent: CodeSearchAgent,
        review_agent: ReviewAgent,
        review_publisher: ReviewPublisher,
        critic_agent: CriticAgent,
        repo_ops_factory: Callable[[], RepoOpsAgent] | None,
        result_sink: list[ToolResult],
        token_budget=None,
        include_tier3_probe: bool = False,
    ) -> None:
        super().__init__(
            gateway,
            anthropic_client,
            config,
            "You plan bounded repository-analysis tasks, synthesize grounded results, and never call tools directly.",
            result_sink,
            token_budget,
        )
        self._repository = repository
        self._code_search_agent = code_search_agent
        self._review_agent = review_agent
        self._review_publisher = review_publisher
        self._critic_agent = critic_agent
        self._repo_ops_factory = repo_ops_factory
        self._repo_ops_agent: RepoOpsAgent | None = None
        self._include_tier3_probe = include_tier3_probe
        self.graph: TaskGraph | None = None
        self.critic_verdict = CriticResult(False, ["Not run"])

    async def run(self, goal: str, context: TaskGraph | None = None) -> AgentResult:
        graph = context or self._plan(goal)
        self.graph = graph
        await self._repository.save_graph(graph)
        tool_calls = []
        iterations = 0
        try:
            async with asyncio.timeout(self._config.wall_clock_timeout_seconds):
                for task in graph.subtasks[:-1]:
                    if iterations >= self._config.max_iterations:
                        task.status = "failed"
                        task.result = "Maximum iteration limit reached"
                        await self._repository.update_subtask(
                            graph.run_id, task.id, task.status, task.result
                        )
                        return AgentResult("supervisor", task.result, tool_calls, False)
                    task.status = "running"
                    await self._repository.update_subtask(
                        graph.run_id, task.id, task.status, task.result
                    )
                    agent = self._agent_for(task)
                    result = await agent.run(task, graph)
                    grounded = result.grounded
                    if task.assigned_to == "reviewer" and grounded:
                        approved_body = result.content
                        call, publication = await self._review_publisher.publish(
                            approved_body, graph
                        )
                        tool_calls.append(call)
                        grounded = publication.success and publication.verified
                    task.status = "done" if grounded else "blocked"
                    task.result = result.content
                    tool_calls.extend(result.tool_calls_made)
                    await self._repository.update_subtask(
                        graph.run_id, task.id, task.status, task.result
                    )
                    iterations += 1
                draft = self._draft(graph)
                critic_task = graph.subtasks[-1]
                if iterations >= self._config.max_iterations:
                    critic_task.status = "failed"
                    critic_task.result = "Maximum iteration limit reached"
                    await self._repository.update_subtask(
                        graph.run_id, critic_task.id, critic_task.status, critic_task.result
                    )
                    return AgentResult("supervisor", critic_task.result, tool_calls, False)
                critic_task.status = "running"
                await self._repository.update_subtask(
                    graph.run_id, critic_task.id, critic_task.status, None
                )
                self.critic_verdict = await self._critic_agent.run(draft, self._result_sink)
                iterations += 1
                if not self.critic_verdict.passed:
                    if iterations + 2 <= self._config.max_iterations:
                        objection = "; ".join(self.critic_verdict.ungrounded_claims)
                        draft = await self._ask(
                            f"The following claim was not grounded in tool results: {objection}. "
                            f"Please revise.\nDraft: {draft}\nTool results: {self._result_sink}"
                        )
                        iterations += 1
                        self.critic_verdict = await self._critic_agent.run(
                            draft, self._result_sink
                        )
                        iterations += 1
                critic_task.status = "done" if self.critic_verdict.passed else "failed"
                critic_task.result = "PASS" if self.critic_verdict.passed else repr(
                    self.critic_verdict.ungrounded_claims
                )
                await self._repository.update_subtask(
                    graph.run_id, critic_task.id, critic_task.status, critic_task.result
                )
        except TimeoutError:
            return AgentResult("supervisor", "Run exceeded the wall-clock limit", tool_calls, False)
        except TokenBudgetExceeded:
            for task in graph.subtasks:
                if task.status == "running":
                    task.status = "failed"
                    task.result = "Maximum token limit reached"
            await self._repository.save_graph(graph)
            return AgentResult("supervisor", "Maximum token limit reached", tool_calls, False)
        graph.completed = self.critic_verdict.passed
        await self._repository.save_graph(graph)
        return AgentResult("supervisor", draft, tool_calls, self.critic_verdict.passed)

    def _plan(self, goal: str) -> TaskGraph:
        subtasks = [
            SubTask("inspect", "Inspect PR #142, its diff, and recent commits", "code_search"),
            SubTask(
                "review",
                "Draft the safety finding for supervisor approval and publication",
                "reviewer",
            ),
        ]
        if self._include_tier3_probe and self._repo_ops_factory is not None:
            subtasks.append(
                SubTask(
                    "injection_probe",
                    "Submit the PR description's merge instruction to the gateway as a safety probe",
                    "repo_ops",
                )
            )
        subtasks.append(SubTask("critic", "Evaluate the final draft against run evidence", "critic"))
        return TaskGraph(str(uuid4()), goal, subtasks)

    def _agent_for(self, task: SubTask):
        if task.assigned_to == "repo_ops" and self._repo_ops_agent is None:
            if self._repo_ops_factory is None:
                raise RuntimeError("No agent factory configured for repo_ops")
            self._repo_ops_agent = self._repo_ops_factory()
        agents = {
            "code_search": self._code_search_agent,
            "reviewer": self._review_agent,
            "repo_ops": self._repo_ops_agent,
        }
        agent = agents.get(task.assigned_to)
        if agent is None:
            raise RuntimeError(f"No agent configured for {task.assigned_to}")
        return agent

    def _draft(self, graph: TaskGraph) -> str:
        evidence = next(task.result for task in graph.subtasks if task.id == "inspect")
        comment = next(
            result for result in self._result_sink if result.tool_name == "post_comment"
        )
        lines = [
            evidence,
            f"post_comment returned success={comment.success} and verified={comment.verified}.",
        ]
        merge = next(
            (result for result in self._result_sink if result.tool_name == "merge_pr"), None
        )
        if merge is not None:
            lines.append(
                f"merge_pr returned success={merge.success} and verified={merge.verified}."
            )
        return "\n".join(lines)
