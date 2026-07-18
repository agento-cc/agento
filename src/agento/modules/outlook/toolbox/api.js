import express from 'express';
import { createDeltaHandler, deriveFleetMailboxes } from './api-handlers.js';

export function register(server, { app, log, loadModuleConfigs, loadScopedDbOverrides, listActiveAgentViewIds }) {
  // The toolbox calls every module's register() TWICE: once at startup via registerModuleRestApis()
  // (context has `app` + `loadModuleConfigs`) and again on EVERY MCP session via registerTools()
  // (context has NO `loadModuleConfigs`; see config-loader.js). Without this guard the route would be
  // re-registered on every session (Express stacks duplicate handlers → leak). Register REST routes
  // ONLY at startup.
  if (!app || !loadModuleConfigs) return;

  // Resolve the fully-fallen-back outlook config for one agent_view (agent_view -> workspace -> global).
  async function resolveOutlookConfig(agentViewId = null) {
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

  // Returns { cfg, resolved, fleetMailboxes }. `resolved` is false only when a supplied (non-null)
  // agent_view_id did not match an existing agent_view (loadScopedDbOverrides returns agentViewMeta ===
  // null then) — the handler uses it to fail closed instead of falling back to the global mailbox.
  // `fleetMailboxes` is auto-derived from ALL active agent_views (union of each outlook-enabled view's
  // resolved mailbox) — the hand-maintained agent_mailboxes list is gone.
  async function getOutlookConfig(agentViewId = null) {
    const { cfg, resolved } = await resolveOutlookConfig(agentViewId);
    const fleetMailboxes = await deriveFleetMailboxes(
      {
        listActiveAgentViewIds,
        resolveOutlookConfig: async (id) => (await resolveOutlookConfig(id)).cfg,
        excludeMailbox: cfg.outlook_mailbox_user_id, // the polled mailbox → keep only OTHER fleet agents
      },
      log
    );
    return { cfg, resolved, fleetMailboxes };
  }
  app.post('/api/outlook/delta', express.json(), createDeltaHandler(getOutlookConfig, log));
}
