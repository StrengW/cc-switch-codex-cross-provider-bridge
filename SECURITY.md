# Security Policy

CodexBridge is a local compatibility layer that can handle Codex routing, provider credentials passed through upstream tools, and diagnostic logs. Please treat authentication data and logs as sensitive.

## Reporting a vulnerability

Please **do not** publish access tokens, API keys, authentication headers, full private logs, or other secrets in a public GitHub Issue.

For a security-sensitive report, prefer GitHub's private vulnerability reporting feature when it is available for this repository. If private reporting is unavailable, open a public Issue containing only a minimal, redacted description and ask for a private contact path before sharing sensitive reproduction material.

A useful report includes:

- CodexBridge version or commit;
- operating system and architecture;
- Codex and CC Switch versions;
- affected provider / route;
- minimal reproduction steps;
- sanitized logs with secrets and personal paths removed.

## Scope

Security reports are especially useful for issues involving credential exposure, unintended network exposure, unsafe local-file writes, privilege escalation, or routing that sends requests to an unexpected upstream.

CodexBridge is currently Beta and is not an officially supported OpenAI or CC Switch component.
