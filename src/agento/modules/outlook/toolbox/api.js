import express from 'express';
import { createUnreadHandler } from './api-handlers.js';

export function register(server, { app, log, loadModuleConfigs, loadScopedDbOverrides }) {
  // The toolbox calls every module's register() TWICE: once at startup via registerModuleRestApis()
  // (context has `app` + `loadModuleConfigs`) and again on EVERY MCP session via registerTools()
  // (context has NO `loadModuleConfigs`; see config-loader.js). Without this guard the route would be
  // re-registered on every session (Express stacks duplicate handlers → leak). Register REST routes
  // ONLY at startup.
  if (!app || !loadModuleConfigs) return;

  // Returns { cfg, resolved }. `resolved` is false only when a supplied (non-null) agent_view_id did
  // not match an existing agent_view (loadScopedDbOverrides returns agentViewMeta === null then) — the
  // handler uses it to fail closed instead of falling back to the global mailbox.
  async function getOutlookConfig(agentViewId = null) {
    let overrides = null;
    let resolved = true; // absent/null id => global scope is a valid resolution
    if (agentViewId != null && loadScopedDbOverrides) {
      const r = await loadScopedDbOverrides(agentViewId);
      overrides = r.overrides;
      resolved = r.agentViewMeta != null;
    }
    const configs = await loadModuleConfigs(overrides);
    return { cfg: configs?.outlook || {}, resolved };
  }
  app.post('/api/outlook/unread', express.json(), createUnreadHandler(getOutlookConfig, log));
}
