class SeedWorkspace:
    """Seed default workspace and agent01 agent_view."""

    def apply(self, conn):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO workspace (code, label) VALUES (%s, %s)",
                ("default", "Default Workspace"),
            )
            cur.execute("SELECT id FROM workspace WHERE code = 'default'")
            ws_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT IGNORE INTO agent_view (workspace_id, code, label) VALUES (%s, %s, %s)",
                (ws_id, "agent01", "Agent 01"),
            )
        conn.commit()

    def require(self):
        return []
