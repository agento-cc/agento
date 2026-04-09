class RenameAgentConfigPrefix:
    """Rename config paths from agent/* to agent_view/* in core_config_data."""

    def apply(self, conn):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE core_config_data SET path = CONCAT('agent_view/', SUBSTRING(path, 7)) "
                "WHERE path LIKE 'agent/%%'"
            )
        conn.commit()

    def require(self):
        return []
