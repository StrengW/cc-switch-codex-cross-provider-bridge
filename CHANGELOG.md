# Changelog

CodexBridge follows semantic public release versions from the repository-root `VERSION` file. Internal component revision labels that may appear in diagnostic logs are implementation markers, not public release versions.

## [0.1.2] - 2026-09-19

### Fixed

- Strengthened third-party tool-history compatibility repair with pair completeness plus adjacency/order validation.
- Restricted strict tool-adjacency repair to the existing HTTP 400/422 compatibility retry path.
- Added conversation- and route-scoped capability learning so successful strict repair can be reused without affecting unrelated Codex conversations.
- Added capability invalidation when a learned strict preflight is rejected upstream.
- Added regression coverage for non-adjacent tool pairs, output-before-call ordering, preflight reuse, and conversation/route isolation.

## [0.1.1] - Unreleased

### Changed

- Aligned README, architecture, compatibility, security, contribution, and release documentation with the current runtime design.
- Added a single public product-version source in `VERSION` and aligned the Windows Installed Apps `DisplayVersion` metadata with it.
- Added release/version consistency checks so a tag must match `v<contents of VERSION>`.
- Added Windows CI coverage for pushes to `main` so the README CI badge reflects current main-branch validation.
- Included version/release documentation in platform release packages.
- Added a project overview that explains the design in interview-ready language.

### Runtime behavior

- **No provider conversion, continuation, compatibility-firewall, routing, watcher, or lifecycle logic is changed in this release-alignment work.**

## [0.1.0] - 2026-09-18

- First public Beta release.
- Windows source-bootstrap Release ZIP with no prebuilt executable.
- macOS Apple Silicon and Intel portable Release ZIPs, published as clearly labeled unsigned artifacts when Apple signing/notarization credentials are unavailable.
- Cross-provider Codex conversation continuity for the tested OpenAI Official, GLM, DeepSeek, and Qwen workflows.
