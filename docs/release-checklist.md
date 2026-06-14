# Release Checklist

This checklist is for a manual GitHub Releases workflow.

## Before Building

1. Confirm the working tree is clean or that you understand any remaining changes.
2. Update the version in `pyproject.toml`.
3. Review `README.md`, `docs/install-on-new-pc.md`, and `profiles/example.template.yaml`.
4. Make sure the release does not depend on private local paths or lab-only configuration.

## Validation

1. Run the test suite you want to gate the release on.
2. Verify the CLI still starts:

```powershell
daq --help
```

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
```
