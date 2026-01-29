#!/bin/bash
set -euo pipefail

# test-toolbox.sh — MCP toolbox test suite: healthcheck + functional tests
# Usage: bin/test-toolbox.sh [--agent-view-id <id>]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONTAINER="agento-toolbox"

# Parse optional --agent-view-id
AGENT_VIEW_ID=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent-view-id)
      AGENT_VIEW_ID="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: bin/test-toolbox.sh [--agent-view-id <id>]"
      exit 1
      ;;
  esac
done

# Build query string
QS="test=true"
if [ -n "$AGENT_VIEW_ID" ]; then
  QS="${QS}&agent_view_id=$AGENT_VIEW_ID"
fi

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

pass=0
fail=0
skip=0

# ============================================================
echo -e "${CYAN}=== Toolbox MCP Test Suite ===${NC}"
if [ -n "$AGENT_VIEW_ID" ]; then
  echo -e "  ${DIM}agent_view_id=${AGENT_VIEW_ID}${NC}"
fi
echo ""

# Check container is running
if ! docker inspect "$CONTAINER" --format='{{.State.Running}}' 2>/dev/null | grep -q true; then
  echo -e "${RED}✗${NC} Container $CONTAINER is not running"
  echo -e "  Run: ${DIM}cd docker && docker compose up -d toolbox${NC}"
  exit 1
fi

# ============================================================
# PHASE 1: Healthcheck — connectivity verification
# ============================================================
echo -e "${CYAN}[1/2] Healthcheck — connectivity verification${NC}"
echo "========================================"

HEALTH_JSON=$(docker exec "$CONTAINER" node -e "
  fetch('http://localhost:3001/health?${QS}')
    .then(r => r.json())
    .then(d => console.log(JSON.stringify(d)))
    .catch(e => { console.error(e.message); process.exit(1); });
" 2>/dev/null) || {
  echo -e "  ${RED}✗${NC} Failed to fetch /health"
  exit 1
}

# Parse health results into structured lines:
#   TOOL <name>                           — registered tool
#   CHECK <status> <name> <detail>        — healthcheck result
HEALTH_OUTPUT=$(docker exec "$CONTAINER" node -e "
  const data = ${HEALTH_JSON};
  for (const tool of data.tools || []) {
    console.log('TOOL ' + tool);
  }
  for (const check of data.checks || []) {
    const ms = check.ms !== undefined ? ' (' + check.ms + 'ms)' : '';
    const err = check.error ? ' — ' + check.error : '';
    console.log('CHECK ' + check.status + ' ' + check.tool + ms + err);
  }
" 2>/dev/null)

# Collect registered tools and healthcheck results
TOOL_LIST=()
while IFS= read -r line; do
  case "$line" in TOOL\ *) TOOL_LIST+=("${line#TOOL }") ;; esac
done <<< "$HEALTH_OUTPUT"

# Build check lookup (tool_name -> "status detail")
_TMPCHECK=$(mktemp -d)
while IFS= read -r line; do
  case "$line" in
    CHECK\ *)
      rest="${line#CHECK }"
      status="${rest%% *}"
      rest="${rest#* }"
      tool="${rest%% *}"
      detail="${rest#* }"
      echo "${status}" > "$_TMPCHECK/${tool}.status"
      printf '%s' "$detail" > "$_TMPCHECK/${tool}.detail"
      ;;
  esac
done <<< "$HEALTH_OUTPUT"

# Display: each registered tool with its healthcheck status
if [ ${#TOOL_LIST[@]} -eq 0 ]; then
  echo -e "  ${RED}✗${NC} No tools registered"
  ((fail++)) || true
else
  for tool in "${TOOL_LIST[@]}"; do
    # Check for exact match or group match (e.g. jira_search matches group "jira")
    _check_status=""
    _check_detail=""
    if [ -f "$_TMPCHECK/${tool}.status" ]; then
      _check_status=$(cat "$_TMPCHECK/${tool}.status")
      _check_detail=$(cat "$_TMPCHECK/${tool}.detail")
    else
      # Check for group match (e.g. "jira" covers "jira_search", "browser" covers "browser_navigate")
      _prefix="${tool%%_*}"
      if [ -f "$_TMPCHECK/${_prefix}.status" ]; then
        _check_status=$(cat "$_TMPCHECK/${_prefix}.status")
        _check_detail=$(cat "$_TMPCHECK/${_prefix}.detail")
      fi
    fi

    case "$_check_status" in
      ok)
        echo -e "  ${GREEN}✓${NC} ${tool}${_check_detail:+ — ${_check_detail}}"
        ((pass++)) || true
        ;;
      fail)
        echo -e "  ${RED}✗${NC} ${tool}${_check_detail:+ — ${_check_detail}}"
        ((fail++)) || true
        ;;
      skip)
        echo -e "  ${YELLOW}⊘${NC} ${tool}${_check_detail:+ — ${_check_detail}}"
        ((skip++)) || true
        ;;
      *)
        # Registered but no healthcheck — show as present
        echo -e "  ${GREEN}✓${NC} ${tool} ${DIM}(registered, no healthcheck)${NC}"
        ((pass++)) || true
        ;;
    esac
  done
fi

rm -rf "${_TMPCHECK:?}"
echo ""

# ============================================================
# PHASE 2: Functional tests — business logic verification
# ============================================================
echo -e "${CYAN}[2/2] Functional tests — business logic verification${NC}"
echo "========================================"

# Pass tool list and QS to Node.js via env vars
TOOLS_JSON=$(printf '%s\n' "${TOOL_LIST[@]}" | docker exec -i "$CONTAINER" node -e "
  let buf = '';
  process.stdin.on('data', d => buf += d);
  process.stdin.on('end', () => {
    const tools = buf.trim().split('\n').filter(Boolean);
    console.log(JSON.stringify(tools));
  });
" 2>/dev/null)

SSE_QS=""
if [ -n "$AGENT_VIEW_ID" ]; then
  SSE_QS="?agent_view_id=$AGENT_VIEW_ID"
fi

TEST_OUTPUT=$(docker exec -i -e "TOOLBOX_QS=${SSE_QS}" -e "TOOLS_JSON=${TOOLS_JSON}" "$CONTAINER" timeout 180 node --input-type=module << 'NODETEST'
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse.js';

const TOOLBOX_URL = 'http://localhost:3001/sse' + (process.env.TOOLBOX_QS || '');
const USER = 'test@example.com';
const tools = JSON.parse(process.env.TOOLS_JSON || '[]');

function hasTool(name) { return tools.includes(name); }

async function callTool(client, name, args, timeoutMs = 15000) {
  const result = await Promise.race([
    client.callTool({ name, arguments: { user: USER, ...args } }),
    new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), timeoutMs)),
  ]);
  const text = result.content?.[0]?.text || '';
  return { text, isError: !!result.isError };
}

// Connect to MCP
const transport = new SSEClientTransport(new URL(TOOLBOX_URL));
const client = new Client({ name: 'test-toolbox', version: '1.0.0' });

try {
  await client.connect(transport);
} catch (err) {
  console.log(`FAIL _connect_ SSE error: ${err.message}`);
  process.exit(1);
}

// --- MySQL tools: INSERT should be blocked ---
const mysqlTools = tools.filter(t => t.startsWith('mysql_'));
for (const tool of mysqlTools) {
  try {
    const { text, isError } = await callTool(client, tool, { query: 'INSERT INTO t VALUES(1)' });
    if (isError && text.includes('Only SELECT')) {
      console.log(`EXPECTED ${tool} BLOCKED (INSERT rejected)`);
    } else {
      console.log(`FAIL ${tool} INSERT should have been blocked`);
    }
  } catch (err) {
    console.log(`FAIL ${tool} ${err.message}`);
  }
}

// --- email_send: whitelist should block unknown recipients ---
if (hasTool('email_send')) {
  try {
    const { text, isError } = await callTool(client, 'email_send', {
      to: 'should-be@blocked.com',
      subject: 'toolbox-test',
      body: 'This should be blocked by whitelist',
    });
    if (isError && text.includes('not in the allowed recipients whitelist')) {
      console.log('EXPECTED email_send BLOCKED (should-be@blocked.com not whitelisted)');
    } else if (!isError) {
      console.log('FAIL email_send should have been blocked but was sent!');
    } else {
      console.log(`FAIL email_send ${text.substring(0, 120)}`);
    }
  } catch (err) {
    console.log(`FAIL email_send ${err.message}`);
  }
}

// --- schedule_followup: past date should be rejected ---
if (hasTool('schedule_followup')) {
  try {
    const { text, isError } = await callTool(client, 'schedule_followup', {
      reference_id: 'TEST-1',
      scheduled_at: '2020-01-01T00:00:00',
      instructions: 'Test follow-up — should be rejected as past date',
    });
    if (isError && text.includes('must be in the future')) {
      console.log('EXPECTED schedule_followup BLOCKED (past date rejected)');
    } else if (!isError) {
      console.log('FAIL schedule_followup should have rejected past date');
    } else {
      console.log(`FAIL schedule_followup ${text.substring(0, 120)}`);
    }
  } catch (err) {
    console.log(`FAIL schedule_followup ${err.message}`);
  }
}

// --- browser_navigate: blocked domain should be rejected ---
if (hasTool('browser_navigate')) {
  try {
    const { text, isError } = await callTool(client, 'browser_navigate', {
      url: 'https://blocked-domain.test',
    }, 15000);
    if (isError && text.includes('not in allowed list')) {
      console.log('EXPECTED browser_navigate BLOCKED (blocked-domain.test not in allowed list)');
    } else if (!isError) {
      console.log('FAIL browser_navigate blocked-domain.test should have been blocked');
    } else {
      console.log(`FAIL browser_navigate ${text.substring(0, 120)}`);
    }
  } catch (err) {
    console.log(`FAIL browser_navigate ${err.message}`);
  }
}

// --- jira write tools: skip (modify data) ---
const JIRA_WRITE_TOOLS = ['jira_add_comment', 'jira_transition_issue', 'jira_assign_issue', 'jira_create_issue', 'jira_update_issue', 'jira_attach_file'];
for (const tool of JIRA_WRITE_TOOLS) {
  if (hasTool(tool)) {
    console.log(`SKIP ${tool} modifies data`);
  }
}

await client.close();
process.exit(0);
NODETEST
) || true

# Parse results and group per tool (one line per tool)
# Use temp files instead of associative arrays (bash 3.x / macOS compatibility)
_TMPDIR=$(mktemp -d)

while IFS= read -r line; do
  status="${line%% *}"
  rest="${line#* }"
  tool="${rest%% *}"
  detail="${rest#* }"

  case "$status" in
    OK|EXPECTED)
      if [ ! -f "$_TMPDIR/$tool.status" ]; then
        echo "$tool" >> "$_TMPDIR/order"
        echo "OK" > "$_TMPDIR/$tool.status"
        printf '%s' "$detail" > "$_TMPDIR/$tool.detail"
      elif [ "$(cat "$_TMPDIR/$tool.status")" = "OK" ]; then
        printf ', %s' "$detail" >> "$_TMPDIR/$tool.detail"
      fi
      ;;
    FAIL)
      if [ ! -f "$_TMPDIR/$tool.status" ]; then
        echo "$tool" >> "$_TMPDIR/order"
      fi
      echo "FAIL" > "$_TMPDIR/$tool.status"
      printf '%s' "$detail" > "$_TMPDIR/$tool.detail"
      ;;
    SKIP)
      if [ ! -f "$_TMPDIR/$tool.status" ]; then
        echo "$tool" >> "$_TMPDIR/order"
        echo "SKIP" > "$_TMPDIR/$tool.status"
        printf '%s' "$detail" > "$_TMPDIR/$tool.detail"
      fi
      ;;
  esac
done <<< "$TEST_OUTPUT"

# Display one line per tool
if [ -f "$_TMPDIR/order" ]; then
  while IFS= read -r tool; do
    _status=$(cat "$_TMPDIR/$tool.status")
    _detail=$(cat "$_TMPDIR/$tool.detail")
    case "$_status" in
      OK)
        echo -e "  ${GREEN}✓${NC} ${tool} — ${_detail}"
        ((pass++)) || true
        ;;
      FAIL)
        echo -e "  ${RED}✗${NC} ${tool} — ${_detail}"
        ((fail++)) || true
        ;;
      SKIP)
        echo -e "  ${YELLOW}⊘${NC} ${tool} — ${_detail}"
        ((skip++)) || true
        ;;
    esac
  done < "$_TMPDIR/order"
fi
rm -rf "${_TMPDIR:?}"

# ============================================================
# Summary
# ============================================================
echo ""
echo "========================================"
echo -e "Result: ${GREEN}${pass} OK${NC}, ${RED}${fail} errors${NC}, ${YELLOW}${skip} skipped${NC}"

[ "$fail" -eq 0 ]
