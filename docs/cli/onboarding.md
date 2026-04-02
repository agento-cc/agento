# Module Onboarding

When `setup:upgrade` detects a module with incomplete onboarding (e.g. missing API credentials), it presents a strict interactive flow. There are three ways to handle onboarding:

## 1. Interactive (default)

Run `agento setup:upgrade` without flags. For each module needing onboarding:

1. You are prompted to **Proceed with onboarding** or **Skip (choose action)**.
2. If onboarding completes successfully, the module is marked as onboarded.
3. If onboarding is incomplete (e.g. invalid credentials), you choose:
   - **Retry** -- re-run the onboarding flow
   - **Disable** -- disable the module and all its dependents
   - **Quit** -- abort `setup:upgrade` entirely

Arrow-key navigation is used when running in a TTY terminal. In non-TTY environments (CI pipes), a numbered fallback is displayed.

When a module is disabled, all modules that transitively depend on it are also disabled automatically.

## 2. CI/CD (skip onboarding)

```bash
agento setup:upgrade --skip-onboarding
```

Bypasses all onboarding prompts. Useful for CI/CD pipelines where interactive input is not available. Modules with incomplete onboarding will remain enabled but unconfigured -- ensure config values are set beforehand via `config:set` or ENV variables.

## 3. Manual (pre-configure)

Set the required config values before running `setup:upgrade`:

```bash
agento config:set jira/jira_host https://mycompany.atlassian.net
agento config:set jira/jira_user user@example.com
agento config:set jira/jira_token <token>
agento config:set jira/jira_assignee_account_id <account_id>
agento config:set jira/jira_projects '["PROJECT_KEY"]'
agento setup:upgrade
```

When `is_complete()` finds all required values present, the onboarding prompt is skipped automatically for that module.
