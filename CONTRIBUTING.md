# Contributing to CodexBridge

Bug reports, compatibility tests, documentation fixes, and focused pull requests are welcome.

## Change boundaries

CodexBridge uses a correctness-first compatibility layer. Keep changes narrowly scoped.

### Runtime/core changes

For changes to provider routing, portable replay, continuation/shadow state, authentication handling, model catalogs, compatibility-firewall behavior, process lifecycle, watcher behavior, or Codex configuration, open an Issue first and describe:

1. the real workflow being fixed;
2. current behavior;
3. expected behavior;
4. Codex / CC Switch / provider versions;
5. whether existing conversations or continuation state can be affected.

The core rule is: **do not damage an existing conversation; prefer a safe fallback when continuation cannot be proven safe.**

### Documentation / metadata / version-only changes

Documentation, public version metadata, changelog, CI badge/trigger, and release-package metadata changes should not be used as an excuse to refactor runtime code. When a runtime file must be touched only to update public display metadata, keep the diff limited to that metadata and preserve the tested behavior.

## Compatibility claims

Only call a provider/model family “regression-tested” when there is a real exercised workflow behind the claim. Untested Responses-compatible providers should be described as **Best effort** until validated.

See [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md).

## Public versioning

The repository-root [`VERSION`](VERSION) file is the public product-version source of truth. A release tag must be `v<VERSION>` and `CHANGELOG.md` should be updated for each public release.

Internal component revision strings may remain different when they identify implementation state or participate in tested runtime update behavior. See [`docs/VERSIONING.md`](docs/VERSIONING.md).

## Local checks

Run the regression suite before submitting a PR:

```bash
python -m pytest tests -q
```

Windows and macOS release packaging are validated by the GitHub Actions workflows under `.github/workflows/`.

## Windows maintainers and macOS executable bits

When committing from Windows, keep the macOS launcher and shell scripts executable in Git:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\maintainer\PrepareGitHubFromWindows.ps1
```

Then confirm the staged mode changes with:

```powershell
git diff --cached --summary
```

## Logs and secrets

Never commit API keys, authentication tokens, provider secrets, private Codex data, or unredacted personal logs. Redact local usernames, filesystem paths, account identifiers, and credentials before attaching diagnostics to an Issue or PR.
