# How To Publish A Release

This document describes the current manual release flow for `daq-cli`.

It is written for the maintainer working from the repository root on Windows.

## 1. What A Release Produces

The project currently publishes an offline Windows release package built from:

- the project wheel
- dependency wheels in `wheelhouse/`
- `install_offline.ps1`
- `README.md`
- `docs/install-on-new-pc.md`
- `profiles/example.template.yaml`

The main end-user asset is:

- `dist\daq_cli-<version>-offline-win-amd64.zip`

## 2. Pre-Release Checks

Before building a release:

1. Make sure your git working tree is clean, or that you intentionally understand any remaining local changes.
2. Update the version in `pyproject.toml`.
3. Review user-facing docs that should match the release:
   - `README.md`
   - `docs/usage.md`
   - `docs/install-on-new-pc.md`
   - `profiles/example.template.yaml`
4. Confirm the release does not depend on lab-private paths, machine-local files, or uncommitted generated data.

Recommended quick checks:

```powershell
git status --short
python -m pytest
```

Also verify the CLI entrypoint still works in your development environment:

```powershell
daq --help
```

If `daq` is not available in the shell, use:

```powershell
$env:PYTHONPATH='src'
python -m daq_cli.main --help
```

## 3. Build The Release

The repository already includes a release build script:

```powershell
.\scripts\build_release.ps1
```

What this script does:

1. Reads the version from `pyproject.toml`
2. Installs or upgrades the `build` frontend
3. Builds the wheel and sdist into a timestamped `dist\staging-...` directory
4. Creates `dist\daq_cli-<version>-offline-win-amd64\`
5. Copies the main wheel and release helper files into that directory
6. Downloads dependency wheels into `wheelhouse\`
7. Creates `dist\daq_cli-<version>-offline-win-amd64.zip`

Important note:

- The script downloads dependency wheels from package indexes, so it needs network access at build time.

## 4. Expected Output

After a successful build, expect these artifacts under `dist\`:

- `daq_cli-<version>-offline-win-amd64.zip`
- `daq_cli-<version>-offline-win-amd64\`
- `staging-<timestamp>\`

The zip file is the main asset to upload to GitHub Releases.

## 5. Sanity Check The Built Package

Before publishing, do a quick inspection:

1. Open `dist\daq_cli-<version>-offline-win-amd64\`
2. Confirm it contains:
   - `daq_cli-<version>-py3-none-any.whl`
   - `install_offline.ps1`
   - `README.md`
   - `install-on-new-pc.md`
   - `example.template.yaml`
   - `wheelhouse\`
3. Optionally extract the zip into a temporary folder and run:

```powershell
.\install_offline.ps1
daq --help
```

If you want a stronger end-to-end check, follow `docs/install-on-new-pc.md` on a clean machine or clean virtual environment.

## 6. Publish On GitHub Releases

Use the repository's GitHub Releases page and create a new release manually.

Recommended sequence:

1. Push the final release commit to the remote branch.
2. Create and push a version tag that matches `pyproject.toml`.
3. Open GitHub Releases.
4. Create a new release from that tag.
5. Upload:
   - `dist\daq_cli-<version>-offline-win-amd64.zip`
6. Write release notes that include:
   - the main user-facing changes
   - any compatibility notes
   - a pointer to `docs/install-on-new-pc.md`
   - a reminder to generate a machine-local profile with `daq profile init`

Suggested release notes template:

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

## 7. Suggested Command Sequence

This is a practical minimal release flow from the repository root:

```powershell
git status --short
python -m pytest
.\scripts\build_release.ps1
```

Then, after checking the output:

```powershell
git tag v<version>
git push origin v<version>
```

Finally:

1. Create the GitHub Release for `v<version>`
2. Upload `dist\daq_cli-<version>-offline-win-amd64.zip`
3. Paste release notes

## 8. Common Pitfalls

- Version updated in code but tag not updated to match
- Docs still showing old wheel filename examples
- Local-only profile values accidentally treated as release defaults
- Build machine has network restrictions, causing dependency wheel download to fail
- Release zip built successfully, but not sanity-checked before upload

## 9. Related Docs

- `docs/release-checklist.md`
- `docs/install-on-new-pc.md`
- `README.md`
