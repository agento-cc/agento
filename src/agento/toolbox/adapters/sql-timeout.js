const DEFAULT_TIMEOUT_SECONDS = 300;

let _configuredSeconds = null;

export function setSqlTimeoutSeconds(seconds) {
  _configuredSeconds = seconds;
}

export function getSqlTimeoutMs() {
  const seconds = _configuredSeconds ?? DEFAULT_TIMEOUT_SECONDS;
  return seconds * 1000;
}
