# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2024-01-01

### Added
- Core framework with Magento-inspired modular architecture
- Job queue consumer with MySQL backend
- Node.js toolbox MCP server (zero-trust credential broker)
- Sandbox container for Claude Code and OpenAI Codex
- Module system: core modules (jira, claude, codex, core, crypt, agent_view)
- 3-level config fallback (ENV, DB, config.json)
- Event-observer system with module-scoped events
- CLI: `bin/agento` with install, reindex, module management, config, tokens
- Setup lifecycle: `setup:upgrade` with schema migrations, data patches, crontab
- AES-256-CBC encryption for obscure config fields
- Ingress identity routing for multi-agent-view support
- Docker Compose deployment with three-container architecture
