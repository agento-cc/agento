import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// State machine in playwright-client.js is module-scoped. We reset it before
// every test via __resetForTests and re-import after vi.resetModules so the
// SDK mocks below are observed by each fresh import.

describe('playwright-client state machine', () => {
  let connectMock;
  let closeMock;
  let listToolsMock;
  let onCloseRef; // captured from the per-test mock Client
  let transportOptsRef; // captured StdioClientTransport constructor options

  beforeEach(() => {
    vi.resetModules();
    vi.useRealTimers();

    onCloseRef = { fn: null };
    transportOptsRef = { opts: null };
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
        constructor(opts) { transportOptsRef.opts = opts; this.stderr = null; }
      },
      // SDK forwards only this curated allowlist to the child — PLAYWRIGHT_BROWSERS_PATH is NOT in it.
      getDefaultEnvironment: () => ({ PATH: '/usr/bin:/bin', HOME: '/home/test' }),
    }));
    vi.doMock('fs/promises', () => ({
      readFile: vi.fn().mockRejectedValue(new Error('ENOENT')),
      writeFile: vi.fn().mockResolvedValue(undefined),
    }));
    vi.doMock('../log.js', () => ({ logToolboxRest: vi.fn() }));
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

  it('onclose after successful connect tags state.lastError with "closed unexpectedly"', async () => {
    const mod = await import('../playwright-client.js');
    mod.__resetForTests();

    await mod.initPlaywright();
    expect(mod.getPlaywrightState().lastError).toBeNull();

    // Simulate the dead-child case: connect succeeded so no connect-level
    // error is in scope when the child later dies. handleClose must still
    // leave a usable marker for the eventual FATAL log + agent message.
    onCloseRef.fn();

    expect(mod.getPlaywrightState().lastError).toBe('Playwright child process closed unexpectedly');
  });

  it('5 successful-connect-then-crash cycles hit state=failed with "closed unexpectedly" lastError', async () => {
    vi.useFakeTimers();
    const mod = await import('../playwright-client.js');
    mod.__resetForTests();

    // Boot once successfully.
    await mod.initPlaywright();
    expect(mod.getPlaywrightState().state).toBe('ready');

    // 5 cycles: fire onclose, advance through backoff so the restart loop
    // reconnects successfully (connectMock still resolves). attempt grows
    // 1 → 2 → 3 → 4 → 5 across the cycles because reconnects happen inside
    // the STABILITY_RESET_MS window.
    const backoffs = [1000, 2000, 4000, 8000, 16000];
    for (let i = 0; i < 5; i++) {
      onCloseRef.fn();
      await vi.advanceTimersByTimeAsync(backoffs[i] + 50);
      await Promise.resolve();
      await Promise.resolve();
    }
    expect(mod.getPlaywrightState()).toMatchObject({ state: 'ready', attempt: 5 });

    // 6th crash pushes scheduleRestart past MAX_ATTEMPTS → failed.
    onCloseRef.fn();
    const s = mod.getPlaywrightState();
    expect(s.state).toBe('failed');
    expect(s.attempt).toBe(5);
    expect(s.lastError).toBe('Playwright child process closed unexpectedly');
  });

  it('spawns the Playwright child with PLAYWRIGHT_BROWSERS_PATH so it finds the baked browsers', async () => {
    // Regression: the SDK forwards only getDefaultEnvironment() to the child,
    // which omits PLAYWRIGHT_BROWSERS_PATH. Without explicit propagation the
    // @playwright/mcp child looks in the empty $HOME/.cache/ms-playwright and
    // every browser tool fails with 'Browser "chromium" is not installed'.
    const prev = process.env.PLAYWRIGHT_BROWSERS_PATH;
    process.env.PLAYWRIGHT_BROWSERS_PATH = '/opt/playwright';
    try {
      const mod = await import('../playwright-client.js');
      mod.__resetForTests();

      await mod.initPlaywright();

      expect(transportOptsRef.opts).toBeTruthy();
      expect(transportOptsRef.opts.env).toBeTruthy();
      expect(transportOptsRef.opts.env.PLAYWRIGHT_BROWSERS_PATH).toBe('/opt/playwright');
      // Base allowlist must survive — npx needs PATH/HOME to launch the child.
      expect(transportOptsRef.opts.env.PATH).toBeTruthy();
    } finally {
      if (prev === undefined) delete process.env.PLAYWRIGHT_BROWSERS_PATH;
      else process.env.PLAYWRIGHT_BROWSERS_PATH = prev;
    }
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

  it('always spawns with a fixed 1280x720 viewport when no session.json is present', async () => {
    // viewport: null (Playwright default) renders at the unpredictable headless
    // window size and makes on-demand video fall back to a tiny 800x600 canvas.
    // A fixed viewport gives crisp, full-frame screenshots and recordings.
    const mod = await import('../playwright-client.js');
    mod.__resetForTests();

    await mod.initPlaywright();

    const args = transportOptsRef.opts.args;
    const idx = args.indexOf('--viewport-size');
    expect(idx).toBeGreaterThan(-1);
    expect(args[idx + 1]).toBe('1280,720');
    expect(mod.getPlaywrightViewport()).toEqual({ width: 1280, height: 720 });
  });

  it('uses session.viewport when session.json provides one (override of the default)', async () => {
    const fs = await import('fs/promises');
    fs.readFile.mockResolvedValueOnce(JSON.stringify({ viewport: { width: 1920, height: 1080 } }));

    const mod = await import('../playwright-client.js');
    mod.__resetForTests();

    await mod.initPlaywright();

    const args = transportOptsRef.opts.args;
    const idx = args.indexOf('--viewport-size');
    expect(args[idx + 1]).toBe('1920,1080');
    expect(mod.getPlaywrightViewport()).toEqual({ width: 1920, height: 1080 });
  });
});
