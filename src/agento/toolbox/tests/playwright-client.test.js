import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// State machine in playwright-client.js is module-scoped. We reset it before
// every test via __resetForTests and re-import after vi.resetModules so the
// SDK mocks below are observed by each fresh import.

describe('playwright-client state machine', () => {
  let connectMock;
  let closeMock;
  let listToolsMock;
  let onCloseRef; // captured from the per-test mock Client

  beforeEach(() => {
    vi.resetModules();
    vi.useRealTimers();

    onCloseRef = { fn: null };
    connectMock = vi.fn().mockResolvedValue(undefined);
    closeMock = vi.fn().mockResolvedValue(undefined);
    listToolsMock = vi.fn().mockResolvedValue({ tools: [] });

    vi.doMock('@modelcontextprotocol/sdk/client/index.js', () => ({
      Client: class {
        constructor() {
          this.connect = connectMock;
          this.close = closeMock;
          this.listTools = listToolsMock;
          Object.defineProperty(this, 'onclose', {
            set(fn) { onCloseRef.fn = fn; },
            get() { return onCloseRef.fn; },
          });
        }
      },
    }));
    vi.doMock('@modelcontextprotocol/sdk/client/stdio.js', () => ({
      StdioClientTransport: class {
        constructor() { this.stderr = null; }
      },
    }));
    vi.doMock('fs/promises', () => ({
      readFile: vi.fn().mockRejectedValue(new Error('ENOENT')),
      writeFile: vi.fn().mockResolvedValue(undefined),
    }));
    vi.doMock('../log.js', () => ({ logToolbox: vi.fn() }));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('starts in state=starting before first init', async () => {
    const mod = await import('../playwright-client.js');
    mod.__resetForTests();
    expect(mod.getPlaywrightState()).toMatchObject({ state: 'starting', attempt: 0, maxAttempts: 5 });
  });

  it('transitions to state=ready after successful init, attempt stays 0', async () => {
    const mod = await import('../playwright-client.js');
    mod.__resetForTests();

    await mod.initPlaywright();

    expect(connectMock).toHaveBeenCalledTimes(1);
    expect(mod.getPlaywrightState()).toMatchObject({ state: 'ready', attempt: 0, lastError: null });
    expect(mod.getPlaywrightClient()).not.toBeNull();
  });

  it('concurrent initPlaywright() reuses the in-flight promise (mutex)', async () => {
    const mod = await import('../playwright-client.js');
    mod.__resetForTests();

    let resolveConnect;
    connectMock.mockImplementation(() => new Promise(r => { resolveConnect = r; }));

    const p1 = mod.initPlaywright();
    const p2 = mod.initPlaywright();
    // Drain microtasks so the in-flight IIFE walks through buildMcpArgs and
    // reaches await newClient.connect() — only then is connectMock observable.
    await new Promise(r => setTimeout(r, 0));

    expect(connectMock).toHaveBeenCalledTimes(1);
    resolveConnect();
    await p1;
    await p2;
    // Even after both resolve, only one connect ever happened.
    expect(connectMock).toHaveBeenCalledTimes(1);
  });

  it('onclose schedules a restart: state=restarting, attempt=1, log includes backoff', async () => {
    vi.useFakeTimers();
    const mod = await import('../playwright-client.js');
    mod.__resetForTests();

    await mod.initPlaywright();
    expect(mod.getPlaywrightState().state).toBe('ready');

    // Simulate Playwright child crash.
    onCloseRef.fn();

    expect(mod.getPlaywrightState()).toMatchObject({ state: 'restarting', attempt: 1, maxAttempts: 5 });
    expect(mod.getPlaywrightClient()).toBeNull();

    // After the 1s backoff, the loop calls initPlaywright again and reconnects.
    connectMock.mockClear();
    await vi.advanceTimersByTimeAsync(1100);
    await Promise.resolve();
    expect(connectMock).toHaveBeenCalledTimes(1);
    expect(mod.getPlaywrightState().state).toBe('ready');
  });

  it('after MAX_ATTEMPTS consecutive connect failures: state=failed, no further connects', async () => {
    vi.useFakeTimers();
    connectMock.mockRejectedValue(new Error('SIGSEGV'));

    const mod = await import('../playwright-client.js');
    mod.__resetForTests();

    // Initial connect fails → triggers scheduleRestart (attempt=1).
    await mod.initPlaywright().catch(() => {});

    // Drive the restart loop through all 5 attempts.
    // Backoffs: 1s, 2s, 4s, 8s, 16s.
    const backoffs = [1000, 2000, 4000, 8000, 16000];
    for (const ms of backoffs) {
      await vi.advanceTimersByTimeAsync(ms + 50);
      // Each iteration may schedule another, so let microtasks drain.
      await Promise.resolve();
    }

    const s = mod.getPlaywrightState();
    expect(s.state).toBe('failed');
    expect(s.attempt).toBe(5);
    expect(s.lastError).toBe('SIGSEGV');

    // No 6th connect attempt — counter past budget.
    const calls = connectMock.mock.calls.length;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(connectMock.mock.calls.length).toBe(calls);
  });

  it('closePlaywright() blocks the restart loop (shuttingDown gate)', async () => {
    vi.useFakeTimers();
    const mod = await import('../playwright-client.js');
    mod.__resetForTests();

    await mod.initPlaywright();
    await mod.closePlaywright();

    connectMock.mockClear();
    // Simulate a late onclose firing after shutdown — should NOT schedule restart.
    onCloseRef.fn();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(connectMock).not.toHaveBeenCalled();
  });

  it('attempt counter resets to 0 after STABILITY_RESET_MS of stable ready', async () => {
    vi.useFakeTimers();
    const mod = await import('../playwright-client.js');
    mod.__resetForTests();

    // First crash bumps attempt to 1.
    await mod.initPlaywright();
    onCloseRef.fn();
    expect(mod.getPlaywrightState().attempt).toBe(1);

    // Recover.
    await vi.advanceTimersByTimeAsync(1100);
    await Promise.resolve();
    expect(mod.getPlaywrightState().state).toBe('ready');
    expect(mod.getPlaywrightState().attempt).toBe(1); // not reset yet

    // After 30s stable, attempt resets to 0.
    await vi.advanceTimersByTimeAsync(30_000);
    expect(mod.getPlaywrightState().attempt).toBe(0);
  });
});
