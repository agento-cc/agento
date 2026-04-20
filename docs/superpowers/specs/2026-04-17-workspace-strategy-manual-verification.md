# Manual verification playbook — workspace build per-source strategy

**Audience:** another LLM or operator executing this step-by-step. Read each step literally. Do not skip setup. Do not reason about the outcome — just run the command and check the assertion exactly as written. If an assertion fails, stop and report which step and what you saw.

## Prerequisites

- `agento` CLI is on `PATH`.
- You are at the repository root: `/Users/mklauza/Projects/Kazar/agento`.
- Docker is installed. MySQL is reachable via `agento`.
- Existing workspace `it` and agent_view `dev_01` are already seeded (confirm with `ls workspace/build/it/dev_01` — should show `builds/` and `current`).

### Start the stack if it isn't running

```bash
cd /Users/mklauza/Projects/Kazar/agento
cd docker && docker compose -f docker-compose.dev.yml ps
# If the table is empty or services are "Exited":
docker compose -f docker-compose.dev.yml up -d
cd ..
```

Wait until `docker compose -f docker/docker-compose.dev.yml ps` shows `cron` and `db` as healthy/running. Retry up to 30 seconds if needed.

### Sanity checks

Run these once before any scenario and confirm each line:

```bash
agento config:list workspace_build                           # must succeed without "service cron is not running"
ls workspace/theme/                                          # must show CLAUDE.md, SOUL.md, app/ at minimum
ls app/code/kazar/workspace/                                 # must show README.md
ls app/code/kazar/skills/                                    # must show at least one skill directory
```

If any line fails, stop and report "prerequisites broken".

---

## Global helpers (copy into shell once per session)

```bash
# Resolve dev_01's DB id so scope-tests can target it.
AV_ID=$(agento config:get agent_view 2>/dev/null | awk '/\[agent_view\] dev_01 \(id=/{print $NF}' | tr -d 'id=)')
# If that parse fails, fall back to a raw SQL query via admin shell or set AV_ID manually.

# Pretty-print the current build tree (up to 3 levels) with symlink targets.
show_build() {
  local build_dir="$1"
  (cd "$build_dir" && ls -la && echo "---modules---" && ls -la modules/ 2>/dev/null && \
   echo "---skills---"  && ls -la .claude/skills/ 2>/dev/null)
}

# Resolve the active build dir on the host.
current_build() { readlink -f workspace/build/it/dev_01/current; }

# Reset all three strategy keys at global scope (revert to defaults).
reset_strategies() {
  agento config:remove workspace_build/strategy/theme   || true
  agento config:remove workspace_build/strategy/modules || true
  agento config:remove workspace_build/strategy/skills  || true
}

# Also reset any scoped overrides from earlier tests
reset_strategies_all_scopes() {
  for scope in default workspace agent_view; do
    for path in theme modules skills; do
      agento config:remove "workspace_build/strategy/$path" --scope="$scope" --scope-id=0 2>/dev/null || true
    done
  done
}
```

---

## Scenario A — single-source strategy matrix

Run each sub-scenario in sequence. **Between sub-scenarios, always call `reset_strategies` and rebuild with `--force`.**

### A1. Baseline — all copy (default)

```bash
reset_strategies
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)
echo "Build dir: $BUILD"
# Assert: no symlinks in theme files, modules, skills
find "$BUILD" -maxdepth 3 -type l | grep -v '/current$' | grep -v '/\.claude/' || echo "PASS: no symlinks (baseline)"
# Assert: real dirs everywhere
[ -d "$BUILD/modules" ] && [ ! -L "$BUILD/modules" ] && echo "PASS: modules/ is real dir"
```

Expected: every `find -type l` match is 0. Script prints `PASS` lines.

### A2. theme=symlink only

```bash
reset_strategies
agento config:set workspace_build/strategy/theme symlink
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)

# Assert theme items are symlinks where unique across layers
[ -L "$BUILD/app" ] && echo "PASS: app is symlink (unique in base)"
# Assert modules are still real
[ ! -L "$BUILD/modules/kazar/README.md" ] && echo "PASS: module file is real (modules=copy)"
# Assert skills still real
find "$BUILD/.claude/skills/" -maxdepth 1 -type l 2>/dev/null && echo "FAIL: skills should be real dirs" || echo "PASS: skills are real dirs"
```

Expected: `app` symlink exists; module README.md is a regular file; no skill dir is a symlink.

### A3. modules=symlink only

```bash
reset_strategies
agento config:set workspace_build/strategy/modules symlink
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)

# Assert module items symlinked under modules/kazar/
[ -L "$BUILD/modules/kazar/README.md" ] && echo "PASS: module README.md is symlink"
# Assert theme root remains real
[ ! -L "$BUILD/app" ] && echo "PASS: theme app/ is real (theme=copy)"
```

### A4. skills=symlink only

```bash
reset_strategies
agento config:set workspace_build/strategy/skills symlink
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)

# Find at least one skill dir as a symlink
ls -la "$BUILD/.claude/skills/" | grep -E '^l' && echo "PASS: at least one skill is symlink"
# Theme + modules still real
[ ! -L "$BUILD/modules/kazar/README.md" ] && echo "PASS: module file is real"
```

### A5. All symlink

```bash
reset_strategies
agento config:set workspace_build/strategy/theme symlink
agento config:set workspace_build/strategy/modules symlink
agento config:set workspace_build/strategy/skills symlink
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)

# Assert symlinks in all three areas
[ -L "$BUILD/app" ] && [ -L "$BUILD/modules/kazar/README.md" ] && echo "PASS: theme + modules symlinked"
ls -la "$BUILD/.claude/skills/" | grep -E '^l' && echo "PASS: skills symlinked"
```

---

## Scenario B — mixed use case (heavy subtree + scoped overlay)

### B1. Heavy dir in theme stays as single symlink

```bash
reset_strategies
# Create a synthetic heavy subtree in theme (only one layer)
mkdir -p workspace/theme/heavy_repo/vendor/acme
echo "binary-blob" > workspace/theme/heavy_repo/vendor/acme/big.bin
echo "README" > workspace/theme/heavy_repo/README.md

agento config:set workspace_build/strategy/theme symlink
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)

# Assert: build/.../heavy_repo is a single symlink (not a copied tree)
[ -L "$BUILD/heavy_repo" ] && echo "PASS: heavy_repo is single symlink"
# Assert: content accessible through the symlink
[ "$(cat $BUILD/heavy_repo/vendor/acme/big.bin)" = "binary-blob" ] && echo "PASS: content readable through symlink"

# Cleanup
rm -rf workspace/theme/heavy_repo
```

### B2. Colliding dir between base and _ws descends to file-level

```bash
reset_strategies
# Create 'testdocs/' in base AND in _it layer (workspace "it")
mkdir -p workspace/theme/testdocs
echo "base-general" > workspace/theme/testdocs/general.md
mkdir -p workspace/theme/_it/testdocs
echo "it-specific" > workspace/theme/_it/testdocs/it_specific.md

agento config:set workspace_build/strategy/theme symlink
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)

# Assert: build/.../testdocs is a REAL dir (because of collision), not a symlink
[ ! -L "$BUILD/testdocs" ] && [ -d "$BUILD/testdocs" ] && echo "PASS: testdocs is real dir (collision descended)"
# Assert: files inside are symlinks
[ -L "$BUILD/testdocs/general.md" ] && [ -L "$BUILD/testdocs/it_specific.md" ] && echo "PASS: file-level symlinks"
# Assert: content resolves correctly
[ "$(cat $BUILD/testdocs/general.md)" = "base-general" ] && echo "PASS: base file reachable"
[ "$(cat $BUILD/testdocs/it_specific.md)" = "it-specific" ] && echo "PASS: _it file reachable"

# Cleanup
rm -rf workspace/theme/testdocs workspace/theme/_it/testdocs
```

### B3. Module scope overlay: latest layer wins

```bash
reset_strategies
# Add scope overlay to kazar module that overrides README.md for dev_01
mkdir -p app/code/kazar/workspace/_it/_dev_01
echo "DEV_01_OVERRIDE" > app/code/kazar/workspace/_it/_dev_01/README.md

agento config:set workspace_build/strategy/modules symlink
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)

# Assert: dev_01 sees the override
[ "$(cat $BUILD/modules/kazar/README.md)" = "DEV_01_OVERRIDE" ] && echo "PASS: override wins via manifest"
# Assert: file is a symlink to the _it/_dev_01 source (not base)
readlink "$BUILD/modules/kazar/README.md" | grep -q '_dev_01/README.md$' && echo "PASS: symlink points to _dev_01 source"

# Cleanup
rm -rf app/code/kazar/workspace/_it
```

---

## Scenario C — layer override correctness

### C1. Symlink strategy with 3-layer override

```bash
reset_strategies
# Create the same file in all three theme layers
mkdir -p workspace/theme/_it/_dev_01
echo "BASE" > workspace/theme/sentinel.md
echo "WS"   > workspace/theme/_it/sentinel.md
echo "AV"   > workspace/theme/_it/_dev_01/sentinel.md

agento config:set workspace_build/strategy/theme symlink
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)

[ -L "$BUILD/sentinel.md" ] && echo "PASS: sentinel is symlink"
[ "$(cat $BUILD/sentinel.md)" = "AV" ] && echo "PASS: agent_view layer wins"
readlink "$BUILD/sentinel.md" | grep -q '_it/_dev_01/sentinel.md$' && echo "PASS: symlink targets _av source"

# Cleanup
rm -f workspace/theme/sentinel.md workspace/theme/_it/sentinel.md workspace/theme/_it/_dev_01/sentinel.md
rmdir workspace/theme/_it/_dev_01 2>/dev/null || true
```

### C2. Copy strategy — same override semantics

```bash
reset_strategies  # defaults to copy
mkdir -p workspace/theme/_it/_dev_01
echo "BASE" > workspace/theme/sentinel.md
echo "WS"   > workspace/theme/_it/sentinel.md
echo "AV"   > workspace/theme/_it/_dev_01/sentinel.md

agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)

[ ! -L "$BUILD/sentinel.md" ] && echo "PASS: real file (copy mode)"
[ "$(cat $BUILD/sentinel.md)" = "AV" ] && echo "PASS: agent_view layer wins"

rm -f workspace/theme/sentinel.md workspace/theme/_it/sentinel.md workspace/theme/_it/_dev_01/sentinel.md
rmdir workspace/theme/_it/_dev_01 2>/dev/null || true
```

---

## Scenario D — safety (instruction writer does not mutate sources)

### D1. AGENTS.md with theme=symlink + DB override

```bash
reset_strategies
echo "# ORIGINAL THEME AGENTS" > workspace/theme/AGENTS.md
agento config:set workspace_build/strategy/theme symlink
agento config:set agent_view/instructions/agents_md "OVERRIDE_FROM_DB" --scope=agent_view --scope-id="$AV_ID"

agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)

# Assert build got the DB override, as a real file
[ "$(cat $BUILD/AGENTS.md)" = "OVERRIDE_FROM_DB" ] && echo "PASS: build AGENTS.md has DB value"
[ ! -L "$BUILD/AGENTS.md" ] && echo "PASS: build AGENTS.md is real (not symlink)"
# CRITICAL: theme source file must NOT have been mutated via followed symlink
[ "$(cat workspace/theme/AGENTS.md)" = "# ORIGINAL THEME AGENTS" ] && echo "PASS: theme source unchanged"

# Cleanup
rm -f workspace/theme/AGENTS.md
agento config:remove agent_view/instructions/agents_md --scope=agent_view --scope-id="$AV_ID"
```

### D2. CLAUDE.md is always rewritten, never follows theme symlink

```bash
reset_strategies
echo "CUSTOM_THEME_CLAUDE" > workspace/theme/CLAUDE.md
agento config:set workspace_build/strategy/theme symlink
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)

# CLAUDE.md is rewritten to pointer content in the build
grep -q "AGENTS.md" "$BUILD/CLAUDE.md" && echo "PASS: build CLAUDE.md is canonical pointer"
[ ! -L "$BUILD/CLAUDE.md" ] && echo "PASS: build CLAUDE.md is real (not symlink)"
# Theme source unchanged
[ "$(cat workspace/theme/CLAUDE.md)" = "CUSTOM_THEME_CLAUDE" ] && echo "PASS: theme CLAUDE.md unchanged"

# Cleanup
rm -f workspace/theme/CLAUDE.md
echo "# CLAUDE config" > workspace/theme/CLAUDE.md  # restore if needed
```

### D3. SOUL.md symlinked when no DB override

```bash
reset_strategies
echo "THEME_SOUL_FINGERPRINT" > workspace/theme/SOUL.md
agento config:set workspace_build/strategy/theme symlink
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)

# Without DB override, SOUL.md in build is a symlink to the theme file
[ -L "$BUILD/SOUL.md" ] && echo "PASS: SOUL.md is symlink (no DB override + symlink strategy)"
[ "$(cat $BUILD/SOUL.md)" = "THEME_SOUL_FINGERPRINT" ] && echo "PASS: content reachable"

# Cleanup
rm -f workspace/theme/SOUL.md
```

---

## Scenario E — checksum invalidation

### E1. Changing a strategy creates a new build

```bash
reset_strategies
agento workspace:build --agent-view dev_01 --force
BEFORE=$(current_build)

agento config:set workspace_build/strategy/theme symlink
agento workspace:build --agent-view dev_01   # no --force
AFTER=$(current_build)

[ "$BEFORE" != "$AFTER" ] && echo "PASS: new build_id created on strategy change"
```

### E2. Same config → cache hit

```bash
agento workspace:build --agent-view dev_01   # build with current strategies
SECOND_RUN=$(current_build)
agento workspace:build --agent-view dev_01   # again, no change
THIRD_RUN=$(current_build)
[ "$SECOND_RUN" = "$THIRD_RUN" ] && echo "PASS: cache hit — no new build"
```

---

## Scenario F — global-scope-only enforcement

### F1. Agent_view-scoped strategy is IGNORED

```bash
reset_strategies_all_scopes
# Set the strategy at agent_view scope only
agento config:set workspace_build/strategy/theme symlink --scope=agent_view --scope-id="$AV_ID"
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)

# Expectation: global scope is unset, so strategy defaults to copy
[ ! -L "$BUILD/app" ] && echo "PASS: agent_view-scoped override correctly ignored"

# Cleanup
agento config:remove workspace_build/strategy/theme --scope=agent_view --scope-id="$AV_ID"
```

### F2. Global scope IS honored

```bash
reset_strategies_all_scopes
agento config:set workspace_build/strategy/theme symlink   # defaults to global scope
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)

[ -L "$BUILD/app" ] && echo "PASS: global-scope override honored"
```

---

## Scenario G — invalid value falls back to copy

```bash
reset_strategies
# Manually insert a bogus value via SQL or config:set accepting string
agento config:set workspace_build/strategy/theme bogus-value
agento workspace:build --agent-view dev_01 --force 2>&1 | tee /tmp/build.log
BUILD=$(current_build)

# Expectation: build succeeds, falls back to copy, warning logged
grep -iq "Invalid.*strategy.*bogus-value" /tmp/build.log && echo "PASS: warning logged"
[ ! -L "$BUILD/app" ] && echo "PASS: behaves as copy"

reset_strategies
```

---

## Scenario H — migration patch

**Only meaningful on a database that still has the old key. Skip if this has already run.**

### H1. Old key → new key

```bash
reset_strategies
# Manually seed the legacy key (the CLI accepts any path)
agento config:set workspace_build/building_strategy symlink
agento config:get workspace_build/building_strategy   # confirm present

agento setup:upgrade

# Assertions
agento config:get workspace_build/building_strategy 2>&1 | grep -iq 'not found\|no value' && echo "PASS: old key deleted"
agento config:get workspace_build/strategy/modules | grep -q symlink && echo "PASS: new key set to old value"
```

### H2. Idempotent re-run

```bash
agento setup:upgrade   # should log nothing about migration this time
agento config:get workspace_build/strategy/modules | grep -q symlink && echo "PASS: value stable"
reset_strategies
```

---

## Scenario I — edge cases

### I1. Disabling a skill removes its entry when skills=symlink

```bash
reset_strategies
agento skill:sync
FIRST_SKILL=$(agento skill:list --agent-view dev_01 2>&1 | awk '/enabled/{print $1; exit}')
echo "Using skill: $FIRST_SKILL"

agento config:set workspace_build/strategy/skills symlink
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)
[ -e "$BUILD/.claude/skills/$FIRST_SKILL" ] && echo "PASS: skill present before disable"

agento skill:disable "$FIRST_SKILL" --agent-view dev_01
agento workspace:build --agent-view dev_01 --force
BUILD=$(current_build)
[ ! -e "$BUILD/.claude/skills/$FIRST_SKILL" ] && echo "PASS: skill absent after disable"

# Restore
agento skill:enable "$FIRST_SKILL" --agent-view dev_01
```

---

## Teardown (always run at the very end)

```bash
reset_strategies_all_scopes
# If any DB override for instructions was left behind:
agento config:remove agent_view/instructions/agents_md --scope=agent_view --scope-id="$AV_ID" 2>/dev/null || true
# Rebuild one last time to leave a clean, default-copy build in place
agento workspace:build --agent-view dev_01 --force
echo "--- final build ---"
current_build
```

---

## Reporting template

When done, report back using exactly this structure:

```
Scenario A1: PASS / FAIL (details)
Scenario A2: PASS / FAIL
...
Scenario I1: PASS / FAIL

Issues found:
- <specific assertion that failed, scenario, what was observed vs expected>
```

Do not invent scenarios not in this file. If an assertion is ambiguous, report AMBIGUOUS with the exact command output you saw.
