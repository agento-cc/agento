from __future__ import annotations

import json
import logging
import re

import pymysql

from agento.framework.bootstrap import get_module_config
from agento.framework.config_resolver import load_db_overrides
from agento.framework.core_config import config_set, config_set_auto_encrypt
from agento.modules.jira.src.toolbox_client import ToolboxAPIError, ToolboxClient

_REQUIRED_KEYS = (
    "jira/jira_token",
    "jira/jira_host",
    "jira/jira_user",
    "jira/jira_assignee_account_id",
    "jira/jira_projects",
)


def _parse_jira_url(url: str) -> tuple[str, str | None]:
    """Extract host and optionally project key from a Jira URL."""
    # Extract host (scheme + netloc)
    match = re.match(r"(https?://[^/]+)", url.strip())
    if not match:
        return url.strip(), None

    host = match.group(1)
    path = url.strip()[len(host):]

    # Try /browse/KEY-123
    issue_match = re.search(r"/browse/([A-Z][A-Z0-9_]+)-\d+", path)
    if issue_match:
        return host, issue_match.group(1)

    # Try /projects/KEY/
    project_match = re.search(r"/projects/([A-Z][A-Z0-9_]+)", path)
    if project_match:
        return host, project_match.group(1)

    return host, None


class JiraOnboarding:
    def is_complete(self, conn: pymysql.Connection) -> bool:
        overrides = load_db_overrides(conn)
        for key in _REQUIRED_KEYS:
            entry = overrides.get(key)
            if not entry or not entry[0]:
                return False
        return True

    def describe(self) -> str:
        return "Configure Jira connection, agent identity, and project keys"

    def run(self, conn: pymysql.Connection, config: dict, logger: logging.Logger) -> None:
        # 1. Check toolbox_url
        jira_config = get_module_config("jira")
        toolbox_url = jira_config.get("toolbox_url") if isinstance(jira_config, dict) else getattr(jira_config, "toolbox_url", None)
        if not toolbox_url:
            print("  Error: jira module toolbox_url not configured. Set CONFIG__JIRA__TOOLBOX_URL env var.")
            return

        # 2. Verify toolbox reachable
        toolbox = ToolboxClient(toolbox_url)
        try:
            toolbox.jira_request("GET", "/rest/api/3/serverInfo")
        except ToolboxAPIError as e:
            print(f"  Error: Jira API error via toolbox: {e}")
            return
        except Exception as e:
            print(f"  Error: Toolbox not reachable at {toolbox_url}: {e}")
            return

        # 3. Collect Jira URL
        url_input = input("  Jira project or issue URL (e.g. https://myteam.atlassian.net/browse/AI-123): ").strip()
        if not url_input:
            print("  Error: URL is required.")
            return

        jira_host, auto_project_key = _parse_jira_url(url_input)

        # 4. Collect credentials
        jira_user = input("  Jira API user email: ").strip()
        if not jira_user:
            print("  Error: Jira API user email is required.")
            return

        jira_token = input("  Jira API token: ").strip()
        if not jira_token:
            print("  Error: Jira API token is required.")
            return

        # 5. Save credentials to DB
        config_set(conn, "jira/jira_host", jira_host)
        config_set(conn, "jira/jira_user", jira_user)
        config_set_auto_encrypt(conn, "jira/jira_token", jira_token)

        # 6. Verify via /myself
        try:
            myself = toolbox.jira_request("GET", "/rest/api/3/myself")
        except ToolboxAPIError as e:
            print(f"  Error: Jira authentication failed: {e}")
            return

        display_name = myself.get("displayName", "")
        account_id = myself.get("accountId", "")
        email = myself.get("emailAddress", "")

        if not account_id:
            print("  Error: Could not detect Jira account ID from /myself response.")
            return

        # 7. Save identity
        config_set(conn, "jira/jira_assignee", display_name)
        config_set(conn, "jira/jira_assignee_account_id", account_id)
        if email:
            config_set(conn, "jira/user", email)

        print(f"  Detected identity: {display_name} ({email or jira_user})")

        # 8. Project keys
        projects = []
        if auto_project_key:
            try:
                toolbox.jira_request("GET", f"/rest/api/3/project/{auto_project_key}")
                projects.append(auto_project_key)
                print(f"  Auto-detected project: {auto_project_key}")
            except ToolboxAPIError as e:
                print(f"  Warning: Auto-detected project '{auto_project_key}' not accessible: {e}")

        additional = input("  Additional project keys (comma-separated, Enter to skip): ").strip()
        if additional:
            for key in additional.split(","):
                key = key.strip()
                if not key:
                    continue
                try:
                    toolbox.jira_request("GET", f"/rest/api/3/project/{key}")
                    if key not in projects:
                        projects.append(key)
                except ToolboxAPIError as e:
                    print(f"  Warning: Project '{key}' not accessible: {e}")

        if not projects:
            print("  Error: At least one valid project key is required.")
            return

        # 9. Save projects and commit
        config_set(conn, "jira/jira_projects", json.dumps(projects))
        conn.commit()

        # 10. Summary
        print("\n  Onboarding complete for jira:")
        print(f"    Host: {jira_host}")
        print(f"    User: {jira_user}")
        print(f"    Identity: {display_name} (account: {account_id})")
        print(f"    Projects: {', '.join(projects)}")
        print("    Config saved to core_config_data")
