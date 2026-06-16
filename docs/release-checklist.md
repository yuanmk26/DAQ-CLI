# Release Checklist

This checklist is for a manual GitHub Releases workflow.

For the full step-by-step process, see `docs/publish-release.md`.

## Before Building

1. Confirm the working tree is clean or that you understand any remaining changes.
2. Update the version in `pyproject.toml`.
3. Review `README.md`, `docs/install-on-new-pc.md`, `docs/usage.md`, `profiles/example.yaml`, and `profiles/example.template.yaml`.
4. Make sure the release does not depend on private local paths or lab-only configuration.

## Validation

1. Run the test suite you want to gate the release on.
2. Verify the CLI still starts:

```powershell
daq --help
```

3. Generate a fresh example profile and confirm the new output config is present:

```powershell
daq profile init .\release-check.yaml
```

4. If the release changes acquisition outputs, run a short smoke test and verify `raw/json/text/log` land in the expected directories.

## Build

Use the local build script:

```powershell
.\scripts\build_release.ps1
```

Or run the equivalent commands manually:

```powershell
python -m pip install -U build
.\scripts\build_release.ps1
```

Expected output:

- `dist\daq_cli-<version>-py3-none-any.whl`
- `dist\daq_cli-<version>-offline-win-amd64.zip`

## Release Assets

Upload these to the GitHub Release page:

- `dist\daq_cli-<version>-offline-win-amd64.zip`

Link or mention these docs in the release notes:

- `docs/install-on-new-pc.md`
- `README.md`

## Suggested Release Notes Template

```text
Highlights:
- <short summary of the most important changes>

Install:
- Download the offline release zip from this release
- Follow docs/install-on-new-pc.md

Configuration:
- Run daq profile init to generate a profile file
- Update device IPs and TCM IP on each PC
- Adjust outputs.raw/json/text/log for the local storage layout if needed
```
