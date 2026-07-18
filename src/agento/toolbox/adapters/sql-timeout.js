const DEFAULT_TIMEOUT_SECONDS = 300;

export function getSqlTimeoutMs(seconds = DEFAULT_TIMEOUT_SECONDS) {
  const parsed = Number(seconds);
  const resolvedSeconds = Number.isFinite(parsed) && parsed >= 0
    ? parsed
    : DEFAULT_TIMEOUT_SECONDS;
  return resolvedSeconds * 1000;
}
