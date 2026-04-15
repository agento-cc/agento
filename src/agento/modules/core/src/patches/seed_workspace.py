class SeedWorkspace:
    """Seed default workspace and agent01 agent_view."""

    def apply(self, conn):
        from agento.framework.workspace import validate_code

        ws_code, av_code = "default", "agent01"
        validate_code(ws_code, "workspace")
        validate_code(av_code, "agent_view")

        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO workspace (code, label) VALUES (%s, %s)",
                (ws_code, "Default Workspace"),
            )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM workspace WHERE code = %s", (ws_code,))
            row = cur.fetchone()
            if not row:
                raise RuntimeError("Failed to seed default workspace")
            cur.execute(
                "INSERT IGNORE INTO agent_view (workspace_id, code, label) VALUES (%s, %s, %s)",
                (row["id"], av_code, "Agent 01"),
            )
        conn.commit()

    def require(self):
        return []
