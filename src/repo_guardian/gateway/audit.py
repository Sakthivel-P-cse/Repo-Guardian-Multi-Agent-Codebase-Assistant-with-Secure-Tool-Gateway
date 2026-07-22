import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from repo_guardian.domain.tool_call import RiskTier, ToolCall


class AuditLoggerPort(Protocol):
    def log(
        self,
        call: ToolCall,
        tier: RiskTier,
        decision: str,
        outcome: str | None,
    ) -> None: ...


class SQLiteAuditLogger:
    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    outcome TEXT,
                    agent_role TEXT NOT NULL
                )
                """
            )

    def log(
        self,
        call: ToolCall,
        tier: RiskTier,
        decision: str,
        outcome: str | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_log (
                    run_id, timestamp, tool_name, parameters_json,
                    tier, decision, outcome, agent_role
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call.run_id,
                    datetime.now(UTC).isoformat(),
                    call.tool_name,
                    json.dumps(call.parameters, sort_keys=True),
                    tier,
                    decision,
                    outcome,
                    call.agent_role,
                ),
            )

    def list_entries(self, run_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM audit_log"
        parameters: tuple[str, ...] = ()
        if run_id is not None:
            query += " WHERE run_id = ?"
            parameters = (run_id,)
        query += " ORDER BY id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]
