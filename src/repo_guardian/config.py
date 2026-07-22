from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    github_token: str = ""
    github_repo: str = "owner/repo"
    pr_number: int = 142
    max_iterations: int = 10
    max_tokens_per_run: int = 100_000
    wall_clock_timeout_seconds: int = 120
    cost_budget_usd: float = 1.0
    db_path: str = "repo_guardian.db"
    model: str = "z-ai/glm-5.2"
    enable_goal_consistency_check: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
