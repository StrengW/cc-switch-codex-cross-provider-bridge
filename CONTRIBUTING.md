# Contributing to CodexBridge

Bug reports, compatibility tests, documentation fixes, and focused pull requests are welcome.

## Before changing runtime behavior

For changes to provider routing, replay / continuation state, authentication handling, model catalogs, lifecycle behavior, or Codex configuration, open an Issue first and describe:

1. the real workflow being fixed;
2. current behavior;
3. expected behavior;
4. Codex / CC Switch / provider versions;
5. whether existing conversations or continuation state can be affected.

The core rule is: **do not damage an existing conversation; prefer a safe fallback when continuation cannot be proven safe.**

## Local checks

Run the regression suite before submitting a PR:

```bash
python -m pytest tests -q
```

Windows release and macOS release packaging are validated by the GitHub Actions workflows under `.github/workflows/`.

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
