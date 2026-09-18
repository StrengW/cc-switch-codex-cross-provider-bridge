# Versioning

## Public product version

The repository-root [`VERSION`](../VERSION) file is the single source of truth for the **public CodexBridge product version**.

A public GitHub Release tag must be exactly:

```text
v<VERSION>
```

For example, if `VERSION` contains `0.1.1`, the release tag must be `v0.1.1`.

The Windows Installed Apps `DisplayVersion` and platform release packages should use the same public version.

## Internal component revisions

Some runtime files still contain internal implementation revision labels such as the Launcher, Bridge, or manager revision. These labels exist to identify a particular component implementation in diagnostics and, in the manager's case, can participate in runtime restart/update decisions.

They are **not** public SemVer releases and should not be compared to the repository `VERSION` value.

In short:

```text
Public product version: VERSION / GitHub tag / Installed Apps DisplayVersion
Internal revision:      component-specific diagnostic or compatibility marker
```

Do not rename or normalize internal revision markers merely for cosmetic consistency when doing so could alter tested runtime behavior.

## Release rule

Before publishing a tag:

1. update `VERSION`;
2. update `CHANGELOG.md`;
3. run the full regression suite;
4. tag the same commit as `v<VERSION>`;
5. let the Windows and macOS workflows build/publish the release assets.

The CI release workflows reject a tag whose version does not match `VERSION`.
