import aiosqlite

from repo_guardian.domain.task import SubTask, TaskGraph, TaskStatus


class SQLiteTaskRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self._db_path) as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_graphs (
                    run_id TEXT PRIMARY KEY,
                    original_goal TEXT NOT NULL,
                    completed INTEGER NOT NULL
                )
                """
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS subtasks (
                    run_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    assigned_to TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (run_id, id),
                    FOREIGN KEY (run_id) REFERENCES task_graphs(run_id)
                )
                """
            )
            await connection.commit()

    async def save_graph(self, graph: TaskGraph) -> None:
        async with aiosqlite.connect(self._db_path) as connection:
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute("BEGIN IMMEDIATE")
            try:
                await connection.execute(
                    """
                    INSERT INTO task_graphs (run_id, original_goal, completed)
                    VALUES (?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        original_goal = excluded.original_goal,
                        completed = excluded.completed
                    """,
                    (graph.run_id, graph.original_goal, int(graph.completed)),
                )
                await connection.execute("DELETE FROM subtasks WHERE run_id = ?", (graph.run_id,))
                await connection.executemany(
                    """
                    INSERT INTO subtasks (
                        run_id, id, description, assigned_to, status, result, position
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            graph.run_id,
                            task.id,
                            task.description,
                            task.assigned_to,
                            task.status,
                            task.result,
                            position,
                        )
                        for position, task in enumerate(graph.subtasks)
                    ],
                )
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise

    async def get_graph(self, run_id: str) -> TaskGraph | None:
        async with aiosqlite.connect(self._db_path) as connection:
            connection.row_factory = aiosqlite.Row
            graph_row = await (
                await connection.execute(
                    "SELECT * FROM task_graphs WHERE run_id = ?", (run_id,)
                )
            ).fetchone()
            if graph_row is None:
                return None
            task_rows = await (
                await connection.execute(
                    "SELECT * FROM subtasks WHERE run_id = ? ORDER BY position", (run_id,)
                )
            ).fetchall()
        subtasks = [
            SubTask(
                id=row["id"],
                description=row["description"],
                assigned_to=row["assigned_to"],
                status=row["status"],
                result=row["result"],
            )
            for row in task_rows
        ]
        return TaskGraph(
            run_id=graph_row["run_id"],
            original_goal=graph_row["original_goal"],
            subtasks=subtasks,
            completed=bool(graph_row["completed"]),
        )

    async def update_subtask(
        self,
        run_id: str,
        subtask_id: str,
        status: TaskStatus,
        result: str | None,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                """
                UPDATE subtasks SET status = ?, result = ?
                WHERE run_id = ? AND id = ?
                """,
                (status, result, run_id, subtask_id),
            )
            if cursor.rowcount != 1:
                await connection.rollback()
                raise KeyError(f"Unknown subtask {subtask_id} for run {run_id}")
            await connection.commit()
