from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    openai_api_key: str
    github_token: str = ""
    github_repo: str = "owner/repo"
    pr_number: int = 142
    max_iterations: int = 10
    max_tokens_per_run: int = 100_000
    wall_clock_timeout_seconds: int = 120
    cost_budget_usd: float = 1.0
    db_path: str = "repo_guardian.db"
    model: str = "gpt-5.6-luna"
    enable_goal_consistency_check: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
