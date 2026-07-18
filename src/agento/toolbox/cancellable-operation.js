function cancellationError() {
  const error = new Error('Operation cancelled');
  error.code = 'OPERATION_CANCELLED';
  return error;
}

export async function runCancellable(operation, {
  signal,
  timeoutMs,
  onCancel = () => {},
} = {}) {
  let cancelled = false;
  let rejectCancellation;
  const cancellation = new Promise((_, reject) => {
    rejectCancellation = reject;
  });
  const cancel = () => {
    if (cancelled) return;
    cancelled = true;
    const error = cancellationError();
    try {
      onCancel();
    } catch (cause) {
      error.cause = cause;
    }
    rejectCancellation(error);
  };

  if (signal?.aborted) cancel();
  else signal?.addEventListener('abort', cancel, { once: true });

  const timer = timeoutMs > 0 ? setTimeout(cancel, timeoutMs) : null;
  timer?.unref?.();
  const pending = Promise.resolve().then(() => operation({ isCancelled: () => cancelled }));

  try {
    return await Promise.race([pending, cancellation]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', cancel);
  }
}
