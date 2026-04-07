import express from 'express';

import { createJiraProxyHandler } from './jira-proxy.js';

export function register(server, { app, log, moduleConfigs, loadModuleConfigs }) {
  // Resolve Jira config per-request from DB (credentials may be saved after startup)
  async function resolveJiraConfig() {
    if (loadModuleConfigs) {
      const configs = await loadModuleConfigs();
      const cfg = configs?.jira || {};
      return {
        host: cfg.jira_host || null,
        user: cfg.jira_user || null,
        token: cfg.jira_token || null,
      };
    }
    const cfg = moduleConfigs?.jira || {};
    return {
      host: cfg.jira_host || null,
      user: cfg.jira_user || null,
      token: cfg.jira_token || null,
    };
  }
  // REST API for internal services (cron sync)
  app.post('/api/jira/search', express.json(), async (req, res) => {
    const { jql, fields = [], maxResults = 50 } = req.body;

    if (!jql) {
      return res.status(400).json({ error: 'jql is required' });
    }

    const config = await resolveJiraConfig();
    const { user, token, host } = config;

    if (!user || !token || !host) {
      return res.status(500).json({ error: 'Jira API not configured (jira_host/jira_user/jira_token)' });
    }

    const auth = Buffer.from(`${user}:${token}`).toString('base64');

    try {
      const response = await fetch(`${host}/rest/api/3/search/jql`, {
        method: 'POST',
        headers: {
          'Authorization': `Basic ${auth}`,
          'Accept': 'application/json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ jql, fields, maxResults }),
      });

      if (!response.ok) {
        const text = await response.text();
        log('api/jira/search', 'ERROR', `HTTP ${response.status}: ${text}`);
        return res.status(response.status).json({ error: text });
      }

      const data = await response.json();
      const count = (data.issues || []).length;
      log('api/jira/search', 'OK', `jql="${jql}" -> ${count} results`);
      res.json(data);
    } catch (err) {
      log('api/jira/search', 'ERROR', err.message);
      res.status(500).json({ error: err.message });
    }
  });

  // REST API for internal services (mention publisher)
  app.post('/api/jira/issue/comments', express.json(), async (req, res) => {
    const { issue_key } = req.body;

    if (!issue_key) {
      return res.status(400).json({ error: 'issue_key is required' });
    }

    const config = await resolveJiraConfig();
    const { user, token, host } = config;

    if (!user || !token || !host) {
      return res.status(500).json({ error: 'Jira API not configured (jira_host/jira_user/jira_token)' });
    }

    const auth = Buffer.from(`${user}:${token}`).toString('base64');

    try {
      const response = await fetch(
        `${host}/rest/api/2/issue/${encodeURIComponent(issue_key)}/comment?maxResults=100`,
        {
          headers: {
            'Authorization': `Basic ${auth}`,
            'Accept': 'application/json',
          },
        },
      );

      if (!response.ok) {
        const text = await response.text();
        log('api/jira/issue/comments', 'ERROR', `HTTP ${response.status}: ${text}`);
        return res.status(response.status).json({ error: text });
      }

      const data = await response.json();
      const comments = (data.comments || []).map((c) => ({
        id: c.id,
        author: {
          displayName: c.author?.displayName,
          emailAddress: c.author?.emailAddress,
          accountId: c.author?.accountId,
        },
        body: c.body,
        created: c.created,
      }));
      log('api/jira/issue/comments', 'OK', `issue=${issue_key} -> ${comments.length} comments`);
      res.json({ comments });
    } catch (err) {
      log('api/jira/issue/comments', 'ERROR', err.message);
      res.status(500).json({ error: err.message });
    }
  });

  // Generic Jira API proxy (for onboarding and admin operations)
  app.post('/api/jira/request', express.json(), createJiraProxyHandler(resolveJiraConfig, log));
}
