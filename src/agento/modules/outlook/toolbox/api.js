import express from 'express';
import { createUnreadHandler } from './api-handlers.js';

export function register(server, { app, log, loadModuleConfigs }) {
  // The toolbox calls every module's register() TWICE: once at startup via registerModuleRestApis()
  // (context has `app` + `loadModuleConfigs`) and again on EVERY MCP session via registerTools()
  // (context has NO `loadModuleConfigs`; see config-loader.js). Without this guard the route would be
  // re-registered on every session (Express stacks duplicate handlers → leak). Register REST routes
  // ONLY at startup.
  if (!app || !loadModuleConfigs) return;

  async function getOutlookConfig() {
    const configs = await loadModuleConfigs(null);
    return configs?.outlook || {};
  }
  app.post('/api/outlook/unread', express.json(), createUnreadHandler(getOutlookConfig, log));
}
