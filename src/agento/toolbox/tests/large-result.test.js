import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';

const ARTIFACTS_DIR = '/workspace/artifacts/ws1/av1/job1';

function mockFs() {
  const written = {};
  vi.doMock('node:fs/promises', () => ({
    writeFile: vi.fn(async (path, data) => { written[path] = data; }),
    mkdir: vi.fn(async () => {}),
  }));
  return written;
}

function mockLog() {
  const calls = [];
  vi.doMock('../log.js', () => ({
    logToolbox: vi.fn((tool, status, details) => { calls.push({ tool, status, details }); }),
    logPublisher: vi.fn(),
  }));
  return calls;
}

// ─── rowsToCsv ──────────────────────────────────────────────────────
describe('rowsToCsv', () => {
  afterEach(() => {
    vi.resetModules();
  });

  async function load() {
    const mod = await import('../adapters/large-result.js');
    return mod.rowsToCsv;
  }

  it('converts simple array of objects to CSV', async () => {
    const rowsToCsv = await load();
    const rows = [
      { name: 'Alice', age: 30 },
      { name: 'Bob', age: 25 },
    ];
    expect(rowsToCsv(rows)).toBe('name,age\nAlice,30\nBob,25');
  });

  it('wraps fields containing commas in double quotes', async () => {
    const rowsToCsv = await load();
    const rows = [{ city: 'Krakow, PL', zip: '30-200' }];
    expect(rowsToCsv(rows)).toBe('city,zip\n"Krakow, PL",30-200');
  });

  it('escapes double quotes by doubling them', async () => {
    const rowsToCsv = await load();
    const rows = [{ desc: 'She said "hello"' }];
    expect(rowsToCsv(rows)).toBe('desc\n"She said ""hello"""');
  });

  it('wraps fields containing newlines', async () => {
    const rowsToCsv = await load();
    const rows = [{ note: 'line1\nline2' }];
    expect(rowsToCsv(rows)).toBe('note\n"line1\nline2"');
  });

  it('handles null and undefined values as empty strings', async () => {
    const rowsToCsv = await load();
    const rows = [{ a: null, b: undefined, c: 0 }];
    expect(rowsToCsv(rows)).toBe('a,b,c\n,,0');
  });

  it('returns empty string for empty array', async () => {
    const rowsToCsv = await load();
    expect(rowsToCsv([])).toBe('');
  });
});

// ─── maybeOffloadRows ───────────────────────────────────────────────
describe('maybeOffloadRows', () => {
  let written = {};
  let mkdirCalls = [];

  beforeEach(() => {
    written = {};
    mkdirCalls = [];
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  async function load(threshold) {
    vi.doMock('node:fs/promises', () => ({
      writeFile: vi.fn(async (path, data) => { written[path] = data; }),
      mkdir: vi.fn(async (path, opts) => { mkdirCalls.push({ path, opts }); }),
    }));

    mockLog();

    const mod = await import('../adapters/large-result.js');
    return (rows, toolName) =>
      mod.maybeOffloadRows(rows, toolName, { artifactsDir: ARTIFACTS_DIR, threshold, sampleRows: 5 });
  }

  it('returns null when serialized size <= threshold', async () => {
    const maybeOffloadRows = await load(99999);
    const rows = [{ a: 1 }, { a: 2 }, { a: 3 }];
    const result = await maybeOffloadRows(rows, 'test_tool');
    expect(result).toBeNull();
  });

  it('returns summary when serialized size > threshold', async () => {
    const maybeOffloadRows = await load(10);
    const rows = [{ name: 'Alice' }, { name: 'Bob' }, { name: 'Charlie' }];
    const result = await maybeOffloadRows(rows, 'mysql_prod');

    expect(result).not.toBeNull();
    expect(result.summary).toContain('3 rows');
    expect(result.summary).toContain(`${ARTIFACTS_DIR}/mcp-results/mysql_prod/`);
    expect(result.summary).toContain('.csv');
    expect(result.summary).toContain('Columns: name');
    expect(result.summary).toContain('Alice');
  });

  it('creates correct directory structure', async () => {
    const maybeOffloadRows = await load(1);
    await maybeOffloadRows([{ x: 1 }, { x: 2 }], 'my_tool');

    expect(mkdirCalls.length).toBeGreaterThanOrEqual(1);
    const dir = mkdirCalls[0].path;
    expect(dir).toBe(`${ARTIFACTS_DIR}/mcp-results/my_tool`);
    expect(mkdirCalls[0].opts).toEqual({ recursive: true });
  });

  it('writes valid CSV content to file', async () => {
    const maybeOffloadRows = await load(1);
    await maybeOffloadRows([{ a: 1, b: 2 }, { a: 3, b: 4 }], 'test_tool');

    const paths = Object.keys(written);
    expect(paths.length).toBe(1);
    expect(paths[0]).toMatch(/\.csv$/);
    expect(written[paths[0]]).toBe('a,b\n1,2\n3,4');
  });

  it('includes first 5 rows in sample', async () => {
    const maybeOffloadRows = await load(10);
    const rows = Array.from({ length: 10 }, (_, i) => ({ id: i }));
    const result = await maybeOffloadRows(rows, 'test_tool');

    expect(result.summary).toContain('id\n0\n1\n2\n3\n4');
    expect(result.summary).not.toContain('\n5\n');
  });

  it('falls back to null on filesystem error', async () => {
    vi.doMock('node:fs/promises', () => ({
      writeFile: vi.fn(async () => { throw new Error('disk full'); }),
      mkdir: vi.fn(async () => {}),
    }));

    mockLog();

    const mod = await import('../adapters/large-result.js');
    const result = await mod.maybeOffloadRows(
      [{ a: 1 }, { a: 2 }],
      'test_tool',
      { artifactsDir: ARTIFACTS_DIR, threshold: 1, sampleRows: 5 },
    );
    expect(result).toBeNull();
  });
});

// ─── maybeOffloadText ───────────────────────────────────────────────
describe('maybeOffloadText', () => {
  let written = {};
  let mkdirCalls = [];

  beforeEach(() => {
    written = {};
    mkdirCalls = [];
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  async function load(threshold) {
    vi.doMock('node:fs/promises', () => ({
      writeFile: vi.fn(async (path, data) => { written[path] = data; }),
      mkdir: vi.fn(async (path, opts) => { mkdirCalls.push({ path, opts }); }),
    }));

    mockLog();

    const mod = await import('../adapters/large-result.js');
    return (text, toolName) =>
      mod.maybeOffloadText(text, toolName, { artifactsDir: ARTIFACTS_DIR, threshold, textPreviewChars: 200 });
  }

  it('returns null when text.length <= threshold', async () => {
    const maybeOffloadText = await load(100);
    const result = await maybeOffloadText('short text', 'test_tool');
    expect(result).toBeNull();
  });

  it('returns summary when text.length > threshold', async () => {
    const maybeOffloadText = await load(10);
    const longText = 'x'.repeat(50);
    const result = await maybeOffloadText(longText, 'jira_search');

    expect(result).not.toBeNull();
    expect(result.summary).toContain('50 chars');
    expect(result.summary).toContain(`${ARTIFACTS_DIR}/mcp-results/jira_search/`);
    expect(result.summary).toContain('.txt');
  });

  it('includes preview of first 200 chars', async () => {
    const maybeOffloadText = await load(10);
    const longText = 'ABCDEFGHIJ'.repeat(30); // 300 chars
    const result = await maybeOffloadText(longText, 'test_tool');

    expect(result.summary).toContain('First 200 chars:');
    const preview = result.summary.split('First 200 chars:\n')[1];
    expect(preview.length).toBe(200);
  });

  it('writes full text content to .txt file', async () => {
    const maybeOffloadText = await load(5);
    const text = 'hello world content';
    await maybeOffloadText(text, 'test_tool');

    const paths = Object.keys(written);
    expect(paths.length).toBe(1);
    expect(paths[0]).toMatch(/\.txt$/);
    expect(written[paths[0]]).toBe(text);
  });

  it('falls back to null on filesystem error', async () => {
    vi.doMock('node:fs/promises', () => ({
      writeFile: vi.fn(async () => { throw new Error('disk full'); }),
      mkdir: vi.fn(async () => {}),
    }));

    mockLog();

    const mod = await import('../adapters/large-result.js');
    const result = await mod.maybeOffloadText(
      'a'.repeat(100),
      'test_tool',
      { artifactsDir: ARTIFACTS_DIR, threshold: 5, textPreviewChars: 200 },
    );
    expect(result).toBeNull();
  });
});

// ─── Integration: MySQL tool with large result ──────────────────────
describe('MySQL tool large result integration', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  async function buildMysqlTool(rowCount, threshold) {
    const rows = Array.from({ length: rowCount }, (_, i) => ({ id: i, name: `row${i}` }));
    const mockQuery = vi.fn().mockResolvedValue([rows]);
    const mockPool = { query: mockQuery };
    vi.doMock('mysql2/promise', () => ({
      default: { createPool: () => mockPool },
    }));

    mockFs();
    const logCalls = mockLog();

    let handler;
    const fakeServer = {
      tool: (_name, _desc, _schema, fn) => { handler = fn; },
    };

    const { registerMysqlTools } = await import('../adapters/mysql.js');
    const offload = { artifactsDir: ARTIFACTS_DIR, threshold, sampleRows: 5 };
    const tools = [{ name: 'mysql_test', description: 'test', config: { host: 'localhost', pass: 'pass', user: 'root', database: 'db' } }];
    registerMysqlTools(fakeServer, tools, { sqlTimeoutSeconds: 300, offload });

    return { handler, mockQuery, logCalls };
  }

  it('returns summary when result size exceeds threshold', async () => {
    const { handler } = await buildMysqlTool(100, 100);
    const result = await handler({ user: 'test@kazar.com', query: 'SELECT id, name FROM t' });

    expect(result.content[0].text).toContain('100 rows');
    expect(result.content[0].text).toContain('.csv');
  });

  it('returns JSON when result size below threshold', async () => {
    const { handler } = await buildMysqlTool(3, 99999);
    const result = await handler({ user: 'test@kazar.com', query: 'SELECT id, name FROM t' });

    const parsed = JSON.parse(result.content[0].text);
    expect(parsed).toHaveLength(3);
    expect(parsed[0]).toEqual({ id: 0, name: 'row0' });
  });

  it('logs QUERY with full SQL before execution', async () => {
    const fullQuery = 'SELECT id, name FROM very_long_table WHERE status = "active" ORDER BY created_at DESC LIMIT 1000';
    const { handler, logCalls } = await buildMysqlTool(3, 99999);
    await handler({ user: 'test@kazar.com', query: fullQuery });

    const queryLog = logCalls.find(c => c.status === 'QUERY');
    expect(queryLog).toBeDefined();
    expect(queryLog.details).toContain(fullQuery);
    expect(queryLog.details).toContain('user=test@kazar.com');
  });

  it('logs OK with execution time after query', async () => {
    const { handler, logCalls } = await buildMysqlTool(3, 99999);
    await handler({ user: 'test@kazar.com', query: 'SELECT 1' });

    const okLog = logCalls.find(c => c.status === 'OK');
    expect(okLog).toBeDefined();
    expect(okLog.details).toMatch(/time=\d+ms/);
    expect(okLog.details).toContain('rows=3');
  });

  it('logs OK with offload=none when below threshold', async () => {
    const { handler, logCalls } = await buildMysqlTool(3, 99999);
    await handler({ user: 'test@kazar.com', query: 'SELECT 1' });

    const okLog = logCalls.find(c => c.status === 'OK');
    expect(okLog.details).toContain('offload=none');
  });

  it('logs OK with offload file path when above threshold', async () => {
    const { handler, logCalls } = await buildMysqlTool(100, 100);
    await handler({ user: 'test@kazar.com', query: 'SELECT 1' });

    const okLog = logCalls.find(c => c.status === 'OK');
    expect(okLog.details).toMatch(new RegExp(`offload=${ARTIFACTS_DIR}/mcp-results/.*\\.csv`));
  });

  it('QUERY log comes before OK log', async () => {
    const { handler, logCalls } = await buildMysqlTool(3, 99999);
    await handler({ user: 'test@kazar.com', query: 'SELECT 1' });

    const queryIdx = logCalls.findIndex(c => c.status === 'QUERY');
    const okIdx = logCalls.findIndex(c => c.status === 'OK');
    expect(queryIdx).toBeLessThan(okIdx);
  });
});

// ─── Integration: MSSQL tool with large result ─────────────────────
describe('MSSQL tool large result integration', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  async function buildMssqlTool(rowCount, threshold) {
    const rows = Array.from({ length: rowCount }, (_, i) => ({ id: i }));
    const mockRequest = {
      timeout: undefined,
      query: vi.fn().mockResolvedValue({ recordset: rows }),
    };
    const mockPool = { request: () => mockRequest };

    vi.doMock('mssql', () => ({
      default: { connect: vi.fn().mockResolvedValue(mockPool) },
    }));

    mockFs();
    const logCalls = mockLog();

    let handler;
    const fakeServer = {
      tool: (_name, _desc, _schema, fn) => { handler = fn; },
    };

    const { registerMssqlTools } = await import('../adapters/mssql.js');
    const offload = { artifactsDir: ARTIFACTS_DIR, threshold, sampleRows: 5 };
    const tools = [{ name: 'mssql_test', description: 'test', config: { host: 'localhost', pass: 'pass', user: 'sa', database: 'db' } }];
    registerMssqlTools(fakeServer, tools, { offload });

    return { handler, logCalls };
  }

  it('returns summary when result size exceeds threshold', async () => {
    const { handler } = await buildMssqlTool(50, 50);
    const result = await handler({ user: 'test@kazar.com', query: 'SELECT 1' });

    expect(result.content[0].text).toContain('50 rows');
    expect(result.content[0].text).toContain('.csv');
  });

  it('returns JSON when result size below threshold', async () => {
    const { handler } = await buildMssqlTool(3, 99999);
    const result = await handler({ user: 'test@kazar.com', query: 'SELECT 1' });

    const parsed = JSON.parse(result.content[0].text);
    expect(parsed).toHaveLength(3);
  });

  it('logs QUERY before and OK with time+offload after', async () => {
    const { handler, logCalls } = await buildMssqlTool(50, 50);
    await handler({ user: 'test@kazar.com', query: 'SELECT TOP 50 * FROM Items' });

    const queryLog = logCalls.find(c => c.status === 'QUERY');
    expect(queryLog).toBeDefined();
    expect(queryLog.details).toContain('SELECT TOP 50 * FROM Items');

    const okLog = logCalls.find(c => c.status === 'OK');
    expect(okLog.details).toMatch(/time=\d+ms/);
    expect(okLog.details).toContain('rows=50');
    expect(okLog.details).toMatch(new RegExp(`offload=${ARTIFACTS_DIR}/.*\\.csv`));
  });
});

// ─── Integration: OpenSearch tool with large result ─────────────────
describe('OpenSearch tool large result integration', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  async function buildOpenSearchTool(hitCount, threshold) {
    const hits = Array.from({ length: hitCount }, (_, i) => ({
      _id: `doc${i}`,
      _source: { sku: `SKU${i}`, price: i * 10 },
    }));
    const responseData = {
      took: 42,
      timed_out: false,
      hits: {
        total: { value: hitCount },
        hits,
      },
    };

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => responseData,
    }));

    mockFs();
    const logCalls = mockLog();

    let handler;
    const fakeServer = {
      tool: (_name, _desc, _schema, fn) => { handler = fn; },
    };

    const { registerOpensearchTools } = await import('../adapters/opensearch.js');
    const offload = { artifactsDir: ARTIFACTS_DIR, threshold, sampleRows: 5 };
    const tools = [{ name: 'os_test', description: 'test', config: { host: 'https://localhost:9200', pass: 'pass', user: 'admin' } }];
    registerOpensearchTools(fakeServer, tools, { offload });

    return { handler, logCalls };
  }

  it('returns summary with metadata when hits exceed threshold', async () => {
    const { handler } = await buildOpenSearchTool(50, 50);
    const result = await handler({ user: 'test@kazar.com', index: 'test_index', query: '{"query":{"match_all":{}}}' });

    expect(result.content[0].text).toContain('OpenSearch: total=50');
    expect(result.content[0].text).toContain('took=42ms');
    expect(result.content[0].text).toContain('50 rows');
    expect(result.content[0].text).toContain('.csv');
  });

  it('returns JSON when hits below threshold', async () => {
    const { handler } = await buildOpenSearchTool(3, 99999);
    const result = await handler({ user: 'test@kazar.com', index: 'test_index', query: '{"query":{"match_all":{}}}' });

    const parsed = JSON.parse(result.content[0].text);
    expect(parsed.hits.hits).toHaveLength(3);
  });

  it('logs QUERY before and OK with time+offload after', async () => {
    const queryBody = '{"query":{"match_all":{}},"size":100}';
    const { handler, logCalls } = await buildOpenSearchTool(50, 50);
    await handler({ user: 'test@kazar.com', index: 'k3-prod_product_1_v*', query: queryBody });

    const queryLog = logCalls.find(c => c.status === 'QUERY');
    expect(queryLog).toBeDefined();
    expect(queryLog.details).toContain('index=k3-prod_product_1_v*');
    expect(queryLog.details).toContain(queryBody);

    const okLog = logCalls.find(c => c.status === 'OK');
    expect(okLog.details).toMatch(/time=\d+ms/);
    expect(okLog.details).toContain('hits=50');
    expect(okLog.details).toMatch(new RegExp(`offload=${ARTIFACTS_DIR}/.*\\.csv`));
  });
});
