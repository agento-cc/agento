import { createHmac, randomBytes } from 'node:crypto';

const DEFAULT_IDLE_TIMEOUT_MS = 30_000;
const DEFAULT_SERVER_CONCURRENCY_BUDGET = 10;
const DEFAULT_SERVER_QUEUE_LIMIT = 100;
const DEFAULT_SERVER_QUEUE_TIMEOUT_MS = 300_000;
const DEFAULT_CLOSE_RETRY_BASE_MS = 1_000;
const DEFAULT_MAX_CLOSE_ATTEMPTS = 3;

function positiveInteger(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function nonNegativeInteger(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : fallback;
}

function queueError(message, code) {
  const error = new Error(message);
  error.code = code;
  return error;
}

export class SqlPoolRegistry {
  constructor({
    idleTimeoutMs = DEFAULT_IDLE_TIMEOUT_MS,
    serverQueueLimit = DEFAULT_SERVER_QUEUE_LIMIT,
    closeRetryBaseMs = DEFAULT_CLOSE_RETRY_BASE_MS,
    maxCloseAttempts = DEFAULT_MAX_CLOSE_ATTEMPTS,
    log = () => {},
  } = {}) {
    this.idleTimeoutMs = nonNegativeInteger(idleTimeoutMs, DEFAULT_IDLE_TIMEOUT_MS);
    this.serverQueueLimit = positiveInteger(serverQueueLimit, DEFAULT_SERVER_QUEUE_LIMIT);
    this.closeRetryBaseMs = nonNegativeInteger(closeRetryBaseMs, DEFAULT_CLOSE_RETRY_BASE_MS);
    this.maxCloseAttempts = positiveInteger(maxCloseAttempts, DEFAULT_MAX_CLOSE_ATTEMPTS);
    this.log = log;
    this.fingerprintKey = randomBytes(32);
    this.entries = new Map();
    this.allEntries = new Set();
    this.failedCloseEntries = new Map();
    this.serverLimiters = new Map();
  }

  poolKey(adapter, toolName, config) {
    return createHmac('sha256', this.fingerprintKey)
      .update(JSON.stringify({ adapter, toolName, config }))
      .digest('hex');
  }

  serverKey(adapter, server) {
    return createHmac('sha256', this.fingerprintKey)
      .update(JSON.stringify({ adapter, server }))
      .digest('hex');
  }

  getServerLimiter(adapter, server, budget) {
    const resolvedBudget = positiveInteger(budget, DEFAULT_SERVER_CONCURRENCY_BUDGET);
    const key = this.serverKey(adapter, server);
    let limiter = this.serverLimiters.get(key);
    if (!limiter) {
      limiter = { key, limit: resolvedBudget, active: 0, queue: [] };
      this.serverLimiters.set(key, limiter);
    } else {
      limiter.limit = Math.min(limiter.limit, resolvedBudget);
    }
    return limiter;
  }

  cleanupWaiter(waiter) {
    clearTimeout(waiter.timer);
    if (waiter.signal && waiter.onAbort) {
      waiter.signal.removeEventListener('abort', waiter.onAbort);
    }
  }

  removeWaiter(limiter, waiter) {
    const index = limiter.queue.indexOf(waiter);
    if (index !== -1) limiter.queue.splice(index, 1);
    this.cleanupWaiter(waiter);
    if (limiter.active === 0 && limiter.queue.length === 0) {
      this.serverLimiters.delete(limiter.key);
    }
  }

  releaseFunction(limiter) {
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.releaseServerSlot(limiter);
    };
  }

  releaseServerSlot(limiter) {
    limiter.active -= 1;
    while (limiter.queue.length > 0 && limiter.active < limiter.limit) {
      const waiter = limiter.queue.shift();
      this.cleanupWaiter(waiter);
      limiter.active += 1;
      waiter.resolve(this.releaseFunction(limiter));
    }
    if (limiter.active === 0 && limiter.queue.length === 0) {
      this.serverLimiters.delete(limiter.key);
    }
  }

  async acquireServerSlot(adapter, server, budget, { signal, waitTimeoutMs } = {}) {
    const limiter = this.getServerLimiter(adapter, server, budget);
    if (limiter.active < limiter.limit) {
      limiter.active += 1;
      return this.releaseFunction(limiter);
    }
    if (limiter.queue.length >= this.serverQueueLimit) {
      throw queueError('SQL server concurrency queue is full', 'SQL_QUEUE_FULL');
    }
    if (signal?.aborted) {
      throw queueError('SQL server concurrency wait was aborted', 'SQL_QUEUE_ABORTED');
    }

    const timeoutMs = nonNegativeInteger(waitTimeoutMs, DEFAULT_SERVER_QUEUE_TIMEOUT_MS);
    return new Promise((resolve, reject) => {
      const waiter = { resolve, reject, signal, onAbort: null, timer: null };
      const cancel = error => {
        this.removeWaiter(limiter, waiter);
        reject(error);
      };

      if (signal) {
        waiter.onAbort = () => cancel(queueError(
          'SQL server concurrency wait was aborted',
          'SQL_QUEUE_ABORTED'
        ));
        signal.addEventListener('abort', waiter.onAbort, { once: true });
      }
      if (timeoutMs > 0) {
        waiter.timer = setTimeout(() => cancel(queueError(
          'SQL server concurrency wait timed out',
          'SQL_QUEUE_TIMEOUT'
        )), timeoutMs);
        waiter.timer.unref?.();
      }
      limiter.queue.push(waiter);
    });
  }

  removeEntry(entry) {
    if (this.entries.get(entry.key) === entry) this.entries.delete(entry.key);
  }

  forgetEntry(entry) {
    clearTimeout(entry.retryTimer);
    entry.retryTimer = null;
    if (this.failedCloseEntries.get(entry.key) === entry) {
      this.failedCloseEntries.delete(entry.key);
    }
    this.allEntries.delete(entry);
  }

  abandonEntry(entry, reason) {
    entry.abandoned = true;
    this.forgetEntry(entry);
    this.log(entry.toolName, 'ERROR', `Stopped tracking ${entry.adapter} pool (${reason})`);
  }

  trackCloseFailure(entry) {
    if (entry.abandoned) return;
    const previous = this.failedCloseEntries.get(entry.key);
    if (previous && previous !== entry) {
      this.abandonEntry(previous, 'superseded failed close');
    }

    if (entry.closeAttempts >= this.maxCloseAttempts) {
      this.abandonEntry(entry, 'close retry limit reached');
      return;
    }

    this.failedCloseEntries.set(entry.key, entry);
    const delay = this.closeRetryBaseMs * (2 ** (entry.closeAttempts - 1));
    entry.retryTimer = setTimeout(() => {
      entry.retryTimer = null;
      this.scheduleClose(entry);
    }, delay);
    entry.retryTimer.unref?.();
  }

  async closeEntry(entry) {
    if (entry.closePromise) return entry.closePromise;

    clearTimeout(entry.idleTimer);
    clearTimeout(entry.retryTimer);
    entry.idleTimer = null;
    entry.retryTimer = null;
    this.removeEntry(entry);
    entry.closeAttempts += 1;
    entry.closePromise = entry.resourcePromise.then(resource => entry.close(resource));
    try {
      await entry.closePromise;
      this.forgetEntry(entry);
    } catch (error) {
      entry.closePromise = null;
      const diagnostic = String(error.code || error.name || 'UNKNOWN').replace(/[^A-Za-z0-9_-]/g, '');
      this.log(entry.toolName, 'ERROR', `Failed to close ${entry.adapter} pool (${diagnostic})`);
      this.trackCloseFailure(entry);
      throw error;
    }
  }

  scheduleClose(entry) {
    void this.closeEntry(entry).catch(() => {});
  }

  scheduleIdleClose(entry) {
    if (entry.active > 0 || entry.closePromise || entry.creationFailed) return;
    if (entry.invalidated || this.entries.get(entry.key) !== entry) {
      this.scheduleClose(entry);
      return;
    }

    clearTimeout(entry.idleTimer);
    entry.idleTimer = setTimeout(() => {
      if (entry.active === 0) this.scheduleClose(entry);
    }, this.idleTimeoutMs);
    entry.idleTimer.unref?.();
  }

  getOrCreateEntry(adapter, toolName, config, create, close) {
    const key = this.poolKey(adapter, toolName, config);
    const existing = this.entries.get(key);
    if (existing) return existing;

    const entry = {
      adapter,
      toolName,
      key,
      active: 0,
      idleTimer: null,
      close,
      closeAttempts: 0,
      closePromise: null,
      creationFailed: false,
      invalidated: false,
      abandoned: false,
      retryTimer: null,
      resourcePromise: null,
    };
    entry.resourcePromise = Promise.resolve()
      .then(create)
      .catch(error => {
        entry.creationFailed = true;
        this.removeEntry(entry);
        this.allEntries.delete(entry);
        throw error;
      });
    this.entries.set(key, entry);
    this.allEntries.add(entry);
    return entry;
  }

  createPoolHandle({
    adapter,
    toolName,
    config,
    server,
    serverConcurrencyBudget = DEFAULT_SERVER_CONCURRENCY_BUDGET,
    queueWaitTimeoutMs = DEFAULT_SERVER_QUEUE_TIMEOUT_MS,
    create,
    close,
  }) {
    let currentEntry = null;

    const getEntry = () => {
      const key = this.poolKey(adapter, toolName, config);
      if (!currentEntry || this.entries.get(key) !== currentEntry) {
        currentEntry = this.getOrCreateEntry(adapter, toolName, config, create, close);
      }
      return currentEntry;
    };

    return {
      use: async (callback, { signal, waitTimeoutMs = queueWaitTimeoutMs } = {}) => {
        const releaseServer = await this.acquireServerSlot(
          adapter,
          server,
          serverConcurrencyBudget,
          { signal, waitTimeoutMs }
        );
        let pool = null;
        try {
          pool = getEntry();
          clearTimeout(pool.idleTimer);
          pool.idleTimer = null;
          pool.active += 1;
          return await callback(await pool.resourcePromise);
        } finally {
          if (pool) {
            pool.active -= 1;
            this.scheduleIdleClose(pool);
          }
          releaseServer();
        }
      },

      invalidate: () => {
        const pool = currentEntry;
        if (!pool || this.entries.get(pool.key) !== pool) return;

        pool.invalidated = true;
        this.removeEntry(pool);
        if (pool.active === 0) this.scheduleClose(pool);
      },
    };
  }

  async closeAll() {
    return Promise.allSettled([...this.allEntries].map(entry => this.closeEntry(entry)));
  }
}
