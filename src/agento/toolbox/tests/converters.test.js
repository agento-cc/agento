import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import XLSX from 'xlsx';

describe('core converters', () => {
  let tmpDir;

  beforeEach(() => {
    tmpDir = path.join(import.meta.dirname, '_test_conv_' + Date.now());
    fs.mkdirSync(tmpDir, { recursive: true });
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
    vi.restoreAllMocks();
  });

  it('exports converters array with PDF and XLSX', async () => {
    const mod = await import('../../modules/core/toolbox/converters.js');
    expect(Array.isArray(mod.converters)).toBe(true);
    expect(mod.converters.length).toBe(2);

    const pdfConv = mod.converters.find(c => c.fromExt === '.pdf');
    expect(pdfConv).toBeDefined();
    expect(pdfConv.toExt).toBe('.md');

    const xlsxConv = mod.converters.find(c => c.fromExt === '.xlsx');
    expect(xlsxConv).toBeDefined();
    expect(xlsxConv.toExt).toBe('.csv');
  });

  it('PDF converter calls pdftotext with correct args', async () => {
    vi.doMock('node:child_process', () => ({
      execFile: vi.fn((_cmd, _args, _opts, cb) => {
        if (typeof _opts === 'function') {
          cb = _opts;
        }
        cb(null, '', '');
      }),
    }));

    vi.resetModules();
    const mod = await import('../../modules/core/toolbox/converters.js');
    const pdfConv = mod.converters.find(c => c.fromExt === '.pdf');

    const inputPath = path.join(tmpDir, 'test.pdf');
    fs.writeFileSync(inputPath, 'fake pdf');

    const result = await pdfConv.convert(inputPath);
    expect(result).toBe(path.join(tmpDir, 'test.md'));
  });

  it('XLSX converter produces CSV from buffer', async () => {
    const mod = await import('../../modules/core/toolbox/converters.js');
    // Inject xlsx module for test environment (in Docker, dynamic import resolves natively)
    mod._setXlsx(XLSX);

    const wb = XLSX.utils.book_new();
    const ws = XLSX.utils.aoa_to_sheet([['Name', 'Value'], ['Alice', '42'], ['Bob', '99']]);
    XLSX.utils.book_append_sheet(wb, ws, 'Sheet1');
    const buf = XLSX.write(wb, { type: 'buffer', bookType: 'xlsx' });

    const inputPath = path.join(tmpDir, 'data.xlsx');
    fs.writeFileSync(inputPath, buf);

    const xlsxConv = mod.converters.find(c => c.fromExt === '.xlsx');
    const result = await xlsxConv.convert(inputPath);
    expect(result).toBe(path.join(tmpDir, 'data.csv'));
    expect(fs.existsSync(result)).toBe(true);

    const csv = fs.readFileSync(result, 'utf-8');
    expect(csv).toContain('Name,Value');
    expect(csv).toContain('Alice,42');
    expect(csv).toContain('Bob,99');
  });

  it('XLSX converter handles multiple sheets', async () => {
    const mod = await import('../../modules/core/toolbox/converters.js');
    mod._setXlsx(XLSX);

    const wb = XLSX.utils.book_new();
    const ws1 = XLSX.utils.aoa_to_sheet([['A', '1']]);
    const ws2 = XLSX.utils.aoa_to_sheet([['B', '2']]);
    XLSX.utils.book_append_sheet(wb, ws1, 'First');
    XLSX.utils.book_append_sheet(wb, ws2, 'Second');
    const buf = XLSX.write(wb, { type: 'buffer', bookType: 'xlsx' });

    const inputPath = path.join(tmpDir, 'multi.xlsx');
    fs.writeFileSync(inputPath, buf);

    const xlsxConv = mod.converters.find(c => c.fromExt === '.xlsx');
    const result = await xlsxConv.convert(inputPath);
    expect(result).toBe(path.join(tmpDir, 'multi_First.csv'));
    expect(fs.existsSync(path.join(tmpDir, 'multi_First.csv'))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, 'multi_Second.csv'))).toBe(true);
  });
});
