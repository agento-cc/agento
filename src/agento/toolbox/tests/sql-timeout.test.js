import { describe, it, expect, vi, afterEach } from 'vitest';

// ─── getSqlTimeoutMs ────────────────────────────────────────────────
describe('getSqlTimeoutMs', () => {
  afterEach(() => {
    vi.resetModules();
  });

  async function load() {
    const mod = await import('../adapters/sql-timeout.js');
    return mod;
  }

  it('returns default 300 000 ms when not configured', async () => {
    const { getSqlTimeoutMs } = await load();
    expect(getSqlTimeoutMs()).toBe(300_000);
  });

  it('returns configured value converted to ms', async () => {
    const { getSqlTimeoutMs, setSqlTimeoutSeconds } = await load();
    setSqlTimeoutSeconds(10);
    expect(getSqlTimeoutMs()).toBe(10_000);
  });

  it('returns 0 ms when configured to 0 (timeout disabled)', async () => {
    const { getSqlTimeoutMs, setSqlTimeoutSeconds } = await load();
    setSqlTimeoutSeconds(0);
    expect(getSqlTimeoutMs()).toBe(0);
  });

  it('returns default when not configured', async () => {
    const { getSqlTimeoutMs } = await load();
    expect(getSqlTimeoutMs()).toBe(300_000);
  });
});

// ─── MySQL tool — timeout passed to pool.query() ───────────────────
describe('MySQL tool timeout', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  async function buildMysqlTool(sqlTimeoutSeconds) {
    // Mock mysql2/promise
    const mockQuery = vi.fn().mockResolvedValue([[{ ok: 1 }]]);
    const mockPool = { query: mockQuery };
    vi.doMock('mysql2/promise', () => ({
      default: { createPool: () => mockPool },
    }));

    let handler;
    const fakeServer = {
      tool: (_name, _desc, _schema, fn) => { handler = fn; },
    };

    const { registerMysqlTools } = await import('../adapters/mysql.js');
    const options = sqlTimeoutSeconds !== null && sqlTimeoutSeconds !== undefined ? { sqlTimeoutSeconds } : {};
    registerMysqlTools(fakeServer, [{
      name: 'mysql_test',
      description: 'Test MySQL',
      config: { host: 'localhost', port: 3306, user: 'user', pass: 'secret', database: 'testdb' },
    }], options);

    return { handler, mockQuery };
  }

  it('passes default timeout (300 000 ms) to pool.query when not configured', async () => {
    const { handler, mockQuery } = await buildMysqlTool(undefined);
    await handler({ user: 'test@example.com', query: 'SELECT 1' });
    expect(mockQuery).toHaveBeenCalledWith({ sql: 'SELECT 1', timeout: 300_000 });
  });

  it('passes custom timeout (5 000 ms) when sqlTimeoutSeconds=5', async () => {
    const { handler, mockQuery } = await buildMysqlTool(5);
    await handler({ user: 'test@example.com', query: 'SELECT 1' });
    expect(mockQuery).toHaveBeenCalledWith({ sql: 'SELECT 1', timeout: 5_000 });
  });
});

// ─── MSSQL tool — timeout set on request object ────────────────────
describe('MSSQL tool timeout', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  async function buildMssqlTool(_sqlTimeoutSeconds) {
    const mockRequest = {
      timeout: undefined,
      query: vi.fn().mockResolvedValue({ recordset: [{ ok: 1 }] }),
    };
    const mockPool = { request: () => mockRequest };

    vi.doMock('mssql', () => ({
      default: { connect: vi.fn().mockResolvedValue(mockPool) },
    }));

    let handler;
    const fakeServer = {
      tool: (_name, _desc, _schema, fn) => { handler = fn; },
    };

    const { registerMssqlTools } = await import('../adapters/mssql.js');
    registerMssqlTools(fakeServer, [{
      name: 'mssql_test',
      description: 'Test MSSQL',
      config: { host: 'localhost', port: 1433, user: 'user', pass: 'secret', database: 'testdb' },
    }]);

    return { handler, mockRequest };
  }

  it('sets default timeout (300 000 ms) on request when not configured', async () => {
    const { handler, mockRequest } = await buildMssqlTool(undefined);
    await handler({ user: 'test@example.com', query: 'SELECT 1' });
    expect(mockRequest.timeout).toBe(300_000);
    expect(mockRequest.query).toHaveBeenCalledWith('SELECT 1');
  });

  it('sets custom timeout (5 000 ms) via setSqlTimeoutSeconds', async () => {
    // Import and configure directly
    const { setSqlTimeoutSeconds } = await import('../adapters/sql-timeout.js');
    setSqlTimeoutSeconds(5);
    const { handler, mockRequest } = await buildMssqlTool(undefined);
    await handler({ user: 'test@example.com', query: 'SELECT 1' });
    expect(mockRequest.timeout).toBe(5_000);
  });
});
