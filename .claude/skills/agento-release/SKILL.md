---
name: agento-release
description: Prepare and publish a new release of Agento. Use this skill when the user wants to release, bump version, create a tag, publish to PyPI, or says things like "let's release", "new version", "bump to X.Y.Z", "cut a release". Even if the user just says "release" with no arguments, use this skill.
---

# Release Workflow

Prepare and publish a new Agento release. This is a sequential, interactive process with human checkpoints.

CRITICAL: Use `gh-saipix` for ALL GitHub CLI operations. NEVER use `gh` directly.

## Step 1: Determine current version

Fetch the latest release tag:
```bash
gh-saipix release list --repo agento-cc/agento --limit 5 --json tagName,isLatest
```

Also read the current version from `pyproject.toml` to confirm they match.

## Step 2: Suggest next versions

Parse the current version X.Y.Z and present three options:

| Bump  | Version         | When to use                          |
|-------|-----------------|--------------------------------------|
| patch | X.Y.(Z+1)      | Bug fixes, small changes             |
| minor | X.(Y+1).0      | New features, backward-compatible    |
| major | (X+1).0.0      | Breaking changes                     |

If the user provided a version as an argument (e.g., `/release 0.2.0`), skip suggestions and use that directly.

## Step 3: Ask user to pick or enter version

Use AskUserQuestion to let the user choose. Accept custom input too.

**Validate the version format:** Must be exactly `X.Y.Z` where X, Y, Z are non-negative integers. Reject anything else (no `v` prefix, no four-part versions, no pre-release suffixes) with a clear message explaining the format.

## Step 4: Bump version in pyproject.toml

Edit the `version = "..."` line in `pyproject.toml` to the new version.

## Step 5: Run uv sync

```bash
uv sync
```

Verify that `uv.lock` was updated by checking `git diff uv.lock` — the old version string should be replaced with the new one. If uv.lock wasn't updated, warn the user.

## Step 6: HITL checkpoint 1 — approve commit, tag, and push

Show the user the full diff:
```bash
git diff pyproject.toml uv.lock
```

Use AskUserQuestion: "Here are the changes for version X.Y.Z. Approve to commit, tag, and push?"

Do NOT proceed without explicit approval.

## Step 7: Commit

```bash
git add pyproject.toml uv.lock
git commit -m "release: vX.Y.Z"
```

Use the exact message format `release: vX.Y.Z`.

## Step 8: Tag and push

```bash
git tag vX.Y.Z
git push origin main
git push origin vX.Y.Z
```

## Step 9: HITL checkpoint 2 — approve GitHub Release creation

Use AskUserQuestion: "v0.X.Y.Z tagged and pushed. Create the GitHub Release now? (This triggers PyPI publish via release.yml workflow)"

Do NOT proceed without explicit approval. The user may want to test locally first.

## Step 10: Create GitHub Release

```bash
gh-saipix release create vX.Y.Z --repo agento-cc/agento --generate-notes --title "vX.Y.Z"
```

This triggers the `release.yml` workflow which automatically runs: test, build, publish to PyPI, attach assets, and smoke test.

Tell the user the release was created and link to the Actions run:
```bash
gh-saipix run list --repo agento-cc/agento --workflow=release.yml --limit 1 --json url
```

## Step 11: Upgrade 
Display info that client can upgrad with command:
```uv tool install --upgrade agento-core```

## Error handling

- If the tag already exists, inform the user and ask if they want to pick a different version.
- If the push fails, do not create the release — ask the user to resolve the issue first.
- If `gh-saipix release create` fails, show the error and suggest the user create the release manually in the GitHub UI.


# PUNISHMENT:
  - NEVER merge or push automatically anything. Only merge/push when you are directly asked to.