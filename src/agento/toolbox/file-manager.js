import { writeFile, mkdir } from 'node:fs/promises';
import { extname, basename, join } from 'node:path';

export class ConverterRegistry {
  #converters = new Map();

  register({ fromExt, toExt, convert }) {
    const ext = fromExt.toLowerCase();
    this.#converters.set(ext, { fromExt: ext, toExt, convert });
  }

  get(ext) {
    return this.#converters.get(ext.toLowerCase()) || null;
  }

  has(ext) {
    return this.#converters.has(ext.toLowerCase());
  }

  all() {
    return new Map(this.#converters);
  }

  clear() {
    this.#converters.clear();
  }
}

export class FileManager {
  #converterRegistry;
  #allowedExtensions;
  #maxFileSize;
  #log;

  constructor({ converterRegistry, allowedExtensions, maxFileSize, log }) {
    this.#converterRegistry = converterRegistry;
    this.#allowedExtensions = allowedExtensions;
    this.#maxFileSize = maxFileSize;
    this.#log = log || (() => {});
  }

  get converterRegistry() {
    return this.#converterRegistry;
  }

  async download(url, filename, { headers, dir, maxSize } = {}) {
    const ext = extname(filename).toLowerCase();
    if (!this.#allowedExtensions.has(ext)) {
      return { skipped: true, skipReason: `Extension ${ext} not allowed` };
    }
    if (maxSize && maxSize > this.#maxFileSize) {
      return { skipped: true, skipReason: `File too large (${maxSize} bytes)` };
    }

    const localPath = join(dir, `${basename(filename, ext)}_${Date.now()}${ext}`);
    try {
      await mkdir(dir, { recursive: true });
      const res = await fetch(url, { headers });
      if (!res.ok) {
        this.#log('file_manager', 'ERROR', `Download failed: ${filename} HTTP ${res.status}`);
        return { skipped: true, skipReason: `Download failed: HTTP ${res.status}` };
      }
      await writeFile(localPath, Buffer.from(await res.arrayBuffer()));
    } catch (err) {
      this.#log('file_manager', 'ERROR', `Write failed: ${filename} -> ${localPath}: ${err.message}`);
      return { skipped: true, skipReason: `Write failed: ${err.message}` };
    }

    let convertedPath = null;
    let conversionError = null;
    const converter = this.#converterRegistry.get(ext);
    if (converter) {
      try {
        convertedPath = await converter.convert(localPath);
        this.#log('file_manager', 'OK', `Converted ${filename} -> ${convertedPath}`);
      } catch (err) {
        conversionError = err.message;
        this.#log('file_manager', 'ERROR', `Conversion failed: ${filename}: ${err.message}`);
      }
    }

    return { localPath, convertedPath, conversionError, skipped: false };
  }
}
