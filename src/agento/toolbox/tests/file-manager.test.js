import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ConverterRegistry, FileManager } from '../file-manager.js';
import fs from 'node:fs';
import path from 'node:path';

describe('ConverterRegistry', () => {
  let registry;

  beforeEach(() => {
    registry = new ConverterRegistry();
  });

  it('registers and retrieves a converter', () => {
    const converter = { fromExt: '.pdf', toExt: '.md', convert: vi.fn() };
    registry.register(converter);
    const result = registry.get('.pdf');
    expect(result).not.toBeNull();
    expect(result.fromExt).toBe('.pdf');
    expect(result.toExt).toBe('.md');
  });

  it('returns null for unregistered extension', () => {
    expect(registry.get('.xyz')).toBeNull();
  });

  it('has() returns true for registered and false for unregistered', () => {
    registry.register({ fromExt: '.pdf', toExt: '.md', convert: vi.fn() });
    expect(registry.has('.pdf')).toBe(true);
    expect(registry.has('.xyz')).toBe(false);
  });

  it('normalizes extensions to lowercase', () => {
    registry.register({ fromExt: '.PDF', toExt: '.md', convert: vi.fn() });
    expect(registry.has('.pdf')).toBe(true);
    expect(registry.get('.PDF')).not.toBeNull();
  });

  it('all() returns a snapshot of registered converters', () => {
    registry.register({ fromExt: '.pdf', toExt: '.md', convert: vi.fn() });
    registry.register({ fromExt: '.xlsx', toExt: '.csv', convert: vi.fn() });
    const all = registry.all();
    expect(all.size).toBe(2);
    expect(all.has('.pdf')).toBe(true);
    expect(all.has('.xlsx')).toBe(true);
  });

  it('clear() removes all converters', () => {
    registry.register({ fromExt: '.pdf', toExt: '.md', convert: vi.fn() });
    registry.clear();
    expect(registry.has('.pdf')).toBe(false);
    expect(registry.all().size).toBe(0);
  });
});

describe('FileManager', () => {
  let tmpDir;
  let registry;

  beforeEach(() => {
    tmpDir = path.join(import.meta.dirname, '_test_fm_' + Date.now());
    fs.mkdirSync(tmpDir, { recursive: true });
    registry = new ConverterRegistry();
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
    vi.restoreAllMocks();
  });

  function createFileManager(opts = {}) {
    return new FileManager({
      converterRegistry: registry,
      allowedExtensions: opts.allowedExtensions || new Set(['.pdf', '.png', '.jpg', '.xlsx', '.csv', '.txt']),
      maxFileSize: opts.maxFileSize || 10_000_000,
      log: opts.log,
    });
  }

  it('skips disallowed extensions', async () => {
    const fm = createFileManager();
    const result = await fm.download('http://example.com/file.exe', 'file.exe', { dir: tmpDir });
    expect(result.skipped).toBe(true);
    expect(result.skipReason).toContain('.exe');
    expect(result.skipReason).toContain('not allowed');
  });

  it('skips oversized files', async () => {
    const fm = createFileManager({ maxFileSize: 1000 });
    const result = await fm.download('http://example.com/file.pdf', 'file.pdf', {
      dir: tmpDir,
      maxSize: 5000,
    });
    expect(result.skipped).toBe(true);
    expect(result.skipReason).toContain('too large');
  });

  it('downloads and returns localPath', async () => {
    const fm = createFileManager();
    const fakeContent = new globalThis.TextEncoder().encode('hello world');

    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      arrayBuffer: () => Promise.resolve(fakeContent.buffer.slice(fakeContent.byteOffset, fakeContent.byteOffset + fakeContent.byteLength)),
    });

    const result = await fm.download('http://example.com/file.txt', 'file.txt', { dir: tmpDir });
    expect(result.skipped).toBe(false);
    expect(result.localPath).toContain('file_');
    expect(result.localPath.endsWith('.txt')).toBe(true);
    expect(result.convertedPath).toBeNull();

    const content = fs.readFileSync(result.localPath);
    expect(content.toString()).toBe('hello world');
  });

  it('converts when converter is registered', async () => {
    const convertFn = vi.fn().mockResolvedValue('/converted/file.md');
    registry.register({ fromExt: '.pdf', toExt: '.md', convert: convertFn });
    const fm = createFileManager();

    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      arrayBuffer: () => Promise.resolve(Buffer.from('pdf content').buffer),
    });

    const result = await fm.download('http://example.com/doc.pdf', 'doc.pdf', { dir: tmpDir });
    expect(result.skipped).toBe(false);
    expect(result.convertedPath).toBe('/converted/file.md');
    expect(convertFn).toHaveBeenCalledOnce();
    expect(convertFn.mock.calls[0][0]).toContain('doc_');
  });

  it('returns convertedPath=null when no converter registered', async () => {
    const fm = createFileManager();

    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      arrayBuffer: () => Promise.resolve(Buffer.from('png data').buffer),
    });

    const result = await fm.download('http://example.com/image.png', 'image.png', { dir: tmpDir });
    expect(result.skipped).toBe(false);
    expect(result.localPath).toContain('.png');
    expect(result.convertedPath).toBeNull();
  });

  it('handles conversion failure gracefully', async () => {
    registry.register({
      fromExt: '.pdf',
      toExt: '.md',
      convert: vi.fn().mockRejectedValue(new Error('pdftotext not found')),
    });
    const fm = createFileManager();

    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      arrayBuffer: () => Promise.resolve(Buffer.from('pdf').buffer),
    });

    const result = await fm.download('http://example.com/doc.pdf', 'doc.pdf', { dir: tmpDir });
    expect(result.skipped).toBe(false);
    expect(result.localPath).toContain('.pdf');
    expect(result.convertedPath).toBeNull();
    expect(result.conversionError).toBe('pdftotext not found');
  });

  it('handles download failure', async () => {
    const fm = createFileManager();

    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: false,
      status: 404,
    });

    const result = await fm.download('http://example.com/file.txt', 'file.txt', { dir: tmpDir });
    expect(result.skipped).toBe(true);
    expect(result.skipReason).toContain('HTTP 404');
  });

  it('passes headers to fetch', async () => {
    const fm = createFileManager();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      arrayBuffer: () => Promise.resolve(Buffer.from('data').buffer),
    });

    const headers = { Authorization: 'Basic abc123' };
    await fm.download('http://example.com/file.txt', 'file.txt', { dir: tmpDir, headers });
    expect(fetchSpy).toHaveBeenCalledWith('http://example.com/file.txt', { headers });
  });

  it('exposes converterRegistry via getter', () => {
    const fm = createFileManager();
    expect(fm.converterRegistry).toBe(registry);
  });

  it('logs and returns skipReason on fetch error', async () => {
    const logSpy = vi.fn();
    const fm = createFileManager({ log: logSpy });

    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('ECONNREFUSED'));

    const result = await fm.download('http://example.com/file.txt', 'file.txt', { dir: tmpDir });
    expect(result.skipped).toBe(true);
    expect(result.skipReason).toMatch(/Write failed/);
    expect(logSpy).toHaveBeenCalledWith('file_manager', 'ERROR', expect.stringContaining('Write failed'));
    expect(logSpy).toHaveBeenCalledWith('file_manager', 'ERROR', expect.stringContaining('ECONNREFUSED'));
  });

  it('returns conversionError when converter throws', async () => {
    registry.register({
      fromExt: '.xlsx',
      toExt: '.csv',
      convert: vi.fn().mockRejectedValue(new Error('Bad archive')),
    });
    const fm = createFileManager();

    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      arrayBuffer: () => Promise.resolve(Buffer.from('xlsx data').buffer),
    });

    const result = await fm.download('http://example.com/data.xlsx', 'data.xlsx', { dir: tmpDir });
    expect(result.skipped).toBe(false);
    expect(result.convertedPath).toBeNull();
    expect(result.conversionError).toBe('Bad archive');
  });

  it('logs converter errors via injected log function', async () => {
    const logSpy = vi.fn();
    registry.register({
      fromExt: '.xlsx',
      toExt: '.csv',
      convert: vi.fn().mockRejectedValue(new Error('Parse error')),
    });
    const fm = createFileManager({ log: logSpy });

    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      arrayBuffer: () => Promise.resolve(Buffer.from('xlsx').buffer),
    });

    await fm.download('http://example.com/sheet.xlsx', 'sheet.xlsx', { dir: tmpDir });
    expect(logSpy).toHaveBeenCalledWith('file_manager', 'ERROR', expect.stringContaining('Parse error'));
  });
});
