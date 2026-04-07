class SeedWorkspace:
    """Seed default workspace and agent01 agent_view."""

    def apply(self, conn):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO workspace (code, label) VALUES (%s, %s)",
                ("default", "Default Workspace"),
            )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM workspace WHERE code = 'default'")
            row = cur.fetchone()
            if not row:
                raise RuntimeError("Failed to seed default workspace")
            cur.execute(
                "INSERT IGNORE INTO agent_view (workspace_id, code, label) VALUES (%s, %s, %s)",
                (row["id"], "agent01", "Agent 01"),
            )
        conn.commit()

    def require(self):
        return []
