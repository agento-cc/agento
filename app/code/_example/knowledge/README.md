# Knowledge Directory

This directory contains module-specific documentation and context that AI agents can reference during task execution.

## What to Include

- **Domain knowledge**: Business rules, data models, API documentation
- **Runbooks**: Step-by-step procedures for common operations
- **Architecture notes**: How this module's systems are structured
- **Troubleshooting guides**: Known issues and their resolutions

## How It's Used

During `bin/agento reindex`, knowledge files are symlinked into the agent workspace. The AI agent can then reference this documentation when working on tasks related to your module.

Files should be in Markdown format for best results.
