import { describe, it, expect, vi } from 'vitest';

import {
  fleetMailboxSet,
  deriveFleetMailboxes,
  isAgentSender,
} from '../../modules/outlook/toolbox/api-handlers.js';

// Bot-to-bot loop suppression uses fleet-address detection (no outbound header stamping): an inbound
// message is agent-authored when its DMARC-verified From is one of the fleet mailboxes. The fleet set
// is auto-derived from the agent_views — the union of each outlook-enabled view's resolved mailbox
// (outlook/outlook_mailbox_user_id through the normal agent_view -> workspace -> global fallback).
describe('fleetMailboxSet (reduce per-view {enabled, mailbox} to a normalized address set)', () => {
  it('unions the mailboxes of enabled views only, normalized (strip + lowercase), deduped', () => {
    const s = fleetMailboxSet([
      { enabled: true, mailbox: 'Bot-A@x.com' },
      { enabled: '1', mailbox: '  bot-b@Y.com ' },
      { enabled: true, mailbox: 'BOT-A@X.COM' }, // duplicate of the first (case/space-insensitive)
    ]);
    expect(s.has('bot-a@x.com')).toBe(true);
    expect(s.has('bot-b@y.com')).toBe(true);
    expect(s.size).toBe(2);
  });

  it('excludes views whose outlook is disabled (every falsy form)', () => {
    const s = fleetMailboxSet([
      { enabled: false, mailbox: 'off-bool@x.com' },
      { enabled: '0', mailbox: 'off-zero@x.com' },
      { enabled: 'false', mailbox: 'off-false@x.com' },
      { enabled: 'False', mailbox: 'off-False@x.com' },
      { enabled: null, mailbox: 'off-null@x.com' },
      { enabled: undefined, mailbox: 'off-undef@x.com' },
      { enabled: '', mailbox: 'off-empty@x.com' },
      { enabled: true, mailbox: 'on@x.com' },
    ]);
    expect(s.size).toBe(1);
    expect(s.has('on@x.com')).toBe(true);
  });

  it('skips enabled views with a missing / blank mailbox', () => {
    const s = fleetMailboxSet([
      { enabled: true, mailbox: '' },
      { enabled: true, mailbox: '   ' },
      { enabled: true, mailbox: null },
      { enabled: true },
      { enabled: true, mailbox: 'real@x.com' },
    ]);
    expect(s.size).toBe(1);
    expect(s.has('real@x.com')).toBe(true);
  });

  it('empty view list → empty set', () => {
    expect(fleetMailboxSet([]).size).toBe(0);
  });
});

describe('deriveFleetMailboxes (enumerate active views -> resolve each -> reduce)', () => {
  it('resolves every active view and dedups shared (global-fallback) mailboxes', async () => {
    const listActiveAgentViewIds = vi.fn(async () => [1, 2, 3]);
    const resolveOutlookConfig = vi.fn(async (id) => ({
      1: { enabled: true, outlook_mailbox_user_id: 'shared@x.com' },
      2: { enabled: true, outlook_mailbox_user_id: 'SHARED@x.com' }, // same global mailbox, different case
      3: { enabled: true, outlook_mailbox_user_id: 'other@x.com' },
    }[id]));
    const set = await deriveFleetMailboxes({ listActiveAgentViewIds, resolveOutlookConfig });
    expect([...set].sort()).toEqual(['other@x.com', 'shared@x.com']);
    expect(resolveOutlookConfig).toHaveBeenCalledTimes(3);
  });

  it('excludes the currently-polled mailbox (keeps only OTHER fleet agents)', async () => {
    const set = await deriveFleetMailboxes({
      listActiveAgentViewIds: async () => [1, 2],
      resolveOutlookConfig: async (id) => ({
        1: { enabled: true, outlook_mailbox_user_id: 'Self@x.com' },
        2: { enabled: true, outlook_mailbox_user_id: 'peer@x.com' },
      }[id]),
      excludeMailbox: 'self@x.com', // case-insensitive
    });
    expect([...set]).toEqual(['peer@x.com']);
  });

  it('drops views whose outlook is disabled', async () => {
    const set = await deriveFleetMailboxes({
      listActiveAgentViewIds: async () => [1, 2],
      resolveOutlookConfig: async (id) => ({
        1: { enabled: false, outlook_mailbox_user_id: 'disabled@x.com' },
        2: { enabled: true, outlook_mailbox_user_id: 'enabled@x.com' },
      }[id]),
    });
    expect([...set]).toEqual(['enabled@x.com']);
  });

  it('FAIL-SAFE: a listing error yields an empty set (no suppression; activation rule still bounds loops)', async () => {
    const log = vi.fn();
    const set = await deriveFleetMailboxes({
      listActiveAgentViewIds: async () => { throw new Error('db down'); },
      resolveOutlookConfig: async () => ({}),
    }, log);
    expect(set.size).toBe(0);
    expect(log).toHaveBeenCalled();
  });

  it('FAIL-SAFE: a per-view resolution error yields an empty set', async () => {
    const set = await deriveFleetMailboxes({
      listActiveAgentViewIds: async () => [1],
      resolveOutlookConfig: async () => { throw new Error('resolve blew up'); },
    }, vi.fn());
    expect(set.size).toBe(0);
  });
});

describe('isAgentSender (match a DMARC-verified From against the fleet set)', () => {
  it('From matching a fleet mailbox (case-insensitive, trimmed) → agent sender', () => {
    const s = fleetMailboxSet([{ enabled: true, mailbox: 'bot-a@x.com' }, { enabled: true, mailbox: 'bot-b@y.com' }]);
    expect(isAgentSender('Bot-A@X.com', s)).toBe(true);
    expect(isAgentSender('  bot-b@y.com  ', s)).toBe(true);
  });

  it('From not in the fleet set (a human, or empty/undefined) → not an agent sender', () => {
    const s = fleetMailboxSet([{ enabled: true, mailbox: 'bot-a@x.com' }]);
    expect(isAgentSender('human@x.com', s)).toBe(false);
    expect(isAgentSender('', s)).toBe(false);
    expect(isAgentSender(undefined, s)).toBe(false);
    expect(isAgentSender('anyone@x.com', new Set())).toBe(false);
  });
});
