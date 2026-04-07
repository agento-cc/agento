import fs from 'fs';
import path from 'path';
import { getCronPool } from './db.js';
import { decrypt, hasEncryptionKey } from './crypto.js';
import { registerAdapterTools } from './adapters/index.js';

const CORE_MODULES_DIR = process.env.CORE_MODULES_DIR || '/app/modules/core';
const USER_MODULES_DIR = process.env.USER_MODULES_DIR || '/app/modules/user';

/**
 * Scan a single modules directory and return parsed module manifests.
 */
function scanDir(dir) {
  if (!fs.existsSync(dir)) return [];

  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const modules = [];

  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith('_')) continue;

    const manifestPath = path.join(dir, entry.name, 'module.json');
    if (!fs.existsSync(manifestPath)) continue;

    try {
      const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
      manifest._path = path.join(dir, entry.name);
      modules.push(manifest);
    } catch (err) {
      console.error(`[config-loader] Failed to load ${manifestPath}: ${err.message}`);
    }
  }

  return modules;
}

/**
 * Scan all module directories (core + user) and return parsed manifests.
 */
export function scanModules() {
  return [...scanDir(CORE_MODULES_DIR), ...scanDir(USER_MODULES_DIR)];
}

/**
 * Read config.json defaults for a module.
 */
function readConfigDefaults(modulePath) {
  const configPath = path.join(modulePath, 'config.json');
  if (!fs.existsSync(configPath)) return {};

  try {
    return JSON.parse(fs.readFileSync(configPath, 'utf-8'));
  } catch (err) {
    console.warn(`[config-loader] Failed to read ${configPath}: ${err.message}`);
    return {};
  }
}

/**
 * Load all core_config_data overrides from DB into a map.
 * Returns { 'path': { value, encrypted } }
 */
async function loadDbOverrides() {
  const overrides = {};
  try {
    const pool = getCronPool();
    const [rows] = await pool.query(
      "SELECT path, value, encrypted FROM core_config_data WHERE scope = 'default' AND scope_id = 0"
    );
    for (const row of rows) {
      overrides[row.path] = { value: row.value, encrypted: !!row.encrypted };
    }
  } catch (err) {
    console.warn(`[config-loader] Failed to load core_config_data: ${err.message}`);
  }
  return overrides;
}

/**
 * Load DB overrides with scoped fallback: global → workspace → agent_view.
 * Returns { overrides, agentViewMeta }.
 */
export async function loadScopedDbOverrides(agentViewId) {
  const overrides = await loadDbOverrides();
  let agentViewMeta = null;

  if (!agentViewId) return { overrides, agentViewMeta };

  try {
    const pool = getCronPool();

    const [avRows] = await pool.query(
      'SELECT id, workspace_id, label FROM agent_view WHERE id = ?',
      [agentViewId]
    );
    if (avRows.length === 0) {
      console.warn(`[config-loader] agent_view_id=${agentViewId} not found, using global config`);
      return { overrides, agentViewMeta };
    }

    const av = avRows[0];
    agentViewMeta = { id: av.id, label: av.label, workspaceId: av.workspace_id };

    // Layer workspace overrides
    const [wsRows] = await pool.query(
      "SELECT path, value, encrypted FROM core_config_data WHERE scope = 'workspace' AND scope_id = ?",
      [av.workspace_id]
    );
    for (const row of wsRows) {
      overrides[row.path] = { value: row.value, encrypted: !!row.encrypted };
    }

    // Layer agent_view overrides (highest priority)
    const [avConfigRows] = await pool.query(
      "SELECT path, value, encrypted FROM core_config_data WHERE scope = 'agent_view' AND scope_id = ?",
      [agentViewId]
    );
    for (const row of avConfigRows) {
      overrides[row.path] = { value: row.value, encrypted: !!row.encrypted };
    }
  } catch (err) {
    console.warn(`[config-loader] Failed to load scoped overrides: ${err.message}`);
  }

  return { overrides, agentViewMeta };
}

/**
 * Check if a tool is enabled via tools/{toolName}/is_enabled config path.
 * Returns false only if explicitly set to '0'. Default = enabled.
 */
export function isToolEnabled(toolName, dbOverrides) {
  const override = dbOverrides[`tools/${toolName}/is_enabled`];
  if (override && override.value === '0') return false;
  return true;
}

/**
 * Resolve a module-level field using 3-level fallback:
 * 1. ENV var: CONFIG__{MODULE}__{FIELD}
 * 2. DB: core_config_data at path {module}/{field}
 * 3. config.json defaults (top-level)
 */
export function resolveModuleField(moduleName, fieldName, configDefaults, dbOverrides) {
  // 1. ENV var (highest priority)
  const envKey = `CONFIG__${moduleName}__${fieldName}`
    .toUpperCase()
    .replace(/-/g, '_');
  if (process.env[envKey] !== undefined) {
    return process.env[envKey];
  }

  // 2. DB override
  const dbPath = `${moduleName}/${fieldName}`.replace(/-/g, '_');
  const override = dbOverrides[dbPath];
  if (override) {
    if (override.encrypted) {
      if (!hasEncryptionKey()) {
        console.warn(`[config-loader] Cannot decrypt ${dbPath}: AGENTO_ENCRYPTION_KEY not set`);
        return null;
      }
      try {
        return decrypt(override.value);
      } catch (err) {
        console.error(`[config-loader] Failed to decrypt ${dbPath}: ${err.message}`);
        return null;
      }
    }
    return override.value;
  }

  // 3. config.json default (top-level, not nested under tools)
  const defaultValue = configDefaults?.[fieldName];
  if (defaultValue !== undefined) return defaultValue;

  return null;
}

/**
 * Resolve a single tool field value using 3-level fallback:
 * 1. ENV var: CONFIG__{MODULE}__TOOLS__{TOOL}__{FIELD}
 * 2. DB: core_config_data (explicit overrides)
 * 3. config.json defaults
 */
function resolveField(moduleName, toolName, fieldName, configDefaults, dbOverrides) {
  // 1. ENV var (highest priority)
  const envKey = `CONFIG__${moduleName}__TOOLS__${toolName}__${fieldName}`
    .toUpperCase()
    .replace(/-/g, '_');
  if (process.env[envKey] !== undefined) {
    return process.env[envKey];
  }

  // 2. DB override
  const dbPath = `${moduleName}/tools/${toolName}/${fieldName}`.replace(/-/g, '_');
  const override = dbOverrides[dbPath];
  if (override) {
    if (override.encrypted) {
      if (!hasEncryptionKey()) {
        console.warn(`[config-loader] Cannot decrypt ${dbPath}: AGENTO_ENCRYPTION_KEY not set`);
        return null;
      }
      try {
        return decrypt(override.value);
      } catch (err) {
        console.error(`[config-loader] Failed to decrypt ${dbPath}: ${err.message}`);
        return null;
      }
    }
    return override.value;
  }

  // 3. config.json default
  const defaultValue = configDefaults?.tools?.[toolName]?.[fieldName];
  if (defaultValue !== undefined) return defaultValue;

  return null;
}

/**
 * Load all tools from all modules with resolved config.
 * Each tool has: { name, type, description, module, config: { host, port, user, pass, database } }
 */
export async function loadTools(dbOverrides = null) {
  const modules = scanModules();
  if (!dbOverrides) dbOverrides = await loadDbOverrides();
  const tools = [];

  for (const mod of modules) {
    const configDefaults = readConfigDefaults(mod._path);

    for (const tool of mod.tools || []) {
      const config = {};
      for (const fieldName of Object.keys(tool.fields || {})) {
        config[fieldName] = resolveField(mod.name, tool.name, fieldName, configDefaults, dbOverrides);
      }

      tools.push({
        name: tool.name,
        type: tool.type,
        description: tool.description,
        module: mod.name,
        config,
      });
    }
  }

  return tools;
}

/**
 * Get tool adapter types registered across all modules.
 */
export function getModuleToolTypes() {
  const modules = scanModules();
  const types = new Set();
  for (const mod of modules) {
    for (const tool of mod.tools || []) {
      types.add(tool.type);
    }
  }
  return types;
}

/**
 * Discover toolbox/*.js files in a module directory.
 * Convention-based: any .js file in toolbox/ is auto-discovered.
 */
function discoverToolboxFiles(modulePath) {
  const toolboxDir = path.join(modulePath, 'toolbox');
  if (!fs.existsSync(toolboxDir)) return [];

  return fs.readdirSync(toolboxDir)
    .filter(f => f.endsWith('.js'))
    .map(f => path.join(toolboxDir, f));
}

/**
 * Register all tools:
 * 1. Config-driven adapter tools (mysql, mssql, opensearch) from module.json
 * 2. Convention-discovered JS tools from module toolbox/ directories
 *
 * @param {object} server - MCP server instance
 * @param {object} context - Shared context { app, log, db, playwright }
 * @returns {string[]} All registered tool names (adapter tools only; module tools are self-registering)
 */
/**
 * Resolve module-level config for all modules that have system.json.
 * Returns { moduleName: { field: resolvedValue } }
 */
export async function loadModuleConfigs(dbOverrides = null) {
  const modules = scanModules();
  if (!dbOverrides) dbOverrides = await loadDbOverrides();
  const moduleConfigs = {};

  for (const mod of modules) {
    const systemPath = path.join(mod._path, 'system.json');
    if (!fs.existsSync(systemPath)) continue;

    let system;
    try {
      system = JSON.parse(fs.readFileSync(systemPath, 'utf-8'));
    } catch {
      continue;
    }
    if (!system || Object.keys(system).length === 0) continue;

    const configDefaults = readConfigDefaults(mod._path);
    const resolved = {};
    for (const fieldName of Object.keys(system)) {
      resolved[fieldName] = resolveModuleField(mod.name, fieldName, configDefaults, dbOverrides);
    }
    moduleConfigs[mod.name] = resolved;
  }

  return moduleConfigs;
}

/**
 * Register module REST API routes on the Express app at startup.
 * This ensures endpoints like /api/jira/request are available before any
 * MCP session connects (needed by setup:upgrade onboarding).
 */
export async function registerModuleRestApis(context) {
  const modules = scanModules();
  const dbOverrides = await loadDbOverrides();
  const moduleConfigs = await loadModuleConfigs(dbOverrides);
  const enrichedContext = { ...context, moduleConfigs, loadModuleConfigs };

  const sorted = [...modules].sort((a, b) => (a.order || 100) - (b.order || 100));

  for (const mod of sorted) {
    const files = discoverToolboxFiles(mod._path);
    for (const file of files) {
      try {
        const toolModule = await import(file);
        if (typeof toolModule.register === 'function') {
          // Pass a stub server — only Express routes matter at startup
          const stubServer = { tool: () => {} };
          await toolModule.register(stubServer, enrichedContext);
          context.log('startup', 'OK', `Registered REST APIs from ${mod.name}/toolbox/${path.basename(file)}`);
        }
      } catch (err) {
        context.log('startup', 'ERROR', `Failed to load ${file}: ${err.message}`);
      }
    }
  }
}

export async function registerTools(server, context, agentViewId = null, preloadedOverrides = null) {
  const modules = scanModules();

  // Use pre-loaded overrides if available, otherwise resolve from DB
  let dbOverrides;
  let agentViewMeta = null;
  if (preloadedOverrides) {
    dbOverrides = preloadedOverrides;
  } else if (agentViewId) {
    ({ overrides: dbOverrides, agentViewMeta } = await loadScopedDbOverrides(agentViewId));
  } else {
    dbOverrides = await loadDbOverrides();
  }

  // Resolve module-level config (system.json fields) — passed to JS tools via context
  const moduleConfigs = await loadModuleConfigs(dbOverrides);
  const enabledCheck = (toolName) => isToolEnabled(toolName, dbOverrides);
  const enrichedContext = { ...context, moduleConfigs, isToolEnabled: enabledCheck };

  // Track all tool names registered on the server (adapter + JS module tools)
  const allToolNames = [];
  const originalTool = server.tool.bind(server);
  server.tool = (...args) => {
    allToolNames.push(args[0]);
    return originalTool(...args);
  };

  // 1. Register config-driven adapter tools (filtered by is_enabled)
  const allTools = await loadTools(dbOverrides);
  const enabledTools = allTools.filter(t => enabledCheck(t.name));
  const moduleToolTypes = getModuleToolTypes();
  const { healthchecks: adapterHealthchecks } = registerAdapterTools(server, enabledTools, moduleToolTypes, moduleConfigs);

  const healthchecks = [...adapterHealthchecks];

  // 2. Discover and register JS tools from modules
  // Sort modules by order field for deterministic registration
  const sorted = [...modules].sort((a, b) => (a.order || 100) - (b.order || 100));

  for (const mod of sorted) {
    const files = discoverToolboxFiles(mod._path);
    for (const file of files) {
      try {
        const toolModule = await import(file);
        if (typeof toolModule.register === 'function') {
          await toolModule.register(server, enrichedContext);
          context.log('discovery', 'OK', `Registered toolbox/${path.basename(file)} from ${mod.name}`);
        } else {
          context.log('discovery', 'SKIP', `${file} has no register() export`);
        }
        if (typeof toolModule.healthcheck === 'function') {
          healthchecks.push(() => toolModule.healthcheck(enrichedContext));
        }
      } catch (err) {
        context.log('discovery', 'ERROR', `Failed to load ${file}: ${err.message}`);
      }
    }
  }

  return { toolNames: allToolNames, healthchecks, agentViewMeta };
}
