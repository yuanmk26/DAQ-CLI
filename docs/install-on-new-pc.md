# Install On A New PC

This guide is for a Windows machine that only needs to use `daq-cli`, not
develop it.

## What To Download

From the GitHub Release page, download:

- `daq_cli-<version>-offline-win-amd64.zip`

You also need:

- Python 3.10 or newer

## Install The Offline Package

Extract the zip, open PowerShell in the extracted folder, and run:

```powershell
.\install_offline.ps1
daq --help
```

Expected result:

- `daq --help` prints the CLI command list

If `daq` is not found in the current shell, activate the virtual environment
again and retry the command.

## Prepare A Machine-Specific Profile

Generate a template profile and create a local machine-specific file:

```powershell
daq profile init .\profiles\lab-pc-01.local.yaml
```

Edit `profiles\lab-pc-01.local.yaml` and update at least:

- `devices.*.ip`
- `tcm.main.ip`

Optional machine-specific values:

- `output_dir`
- default capture settings under `defaults.acquire_single`
- default capture settings under `defaults.acquire_multi`

Recommended pattern:

- keep the wheel and the profile in the same working directory
- create one `.local.yaml` per machine
- do not commit `.local.yaml` back to git

## First Validation

Run a low-risk command first:

```powershell
daq board info dev1 --profile .\profiles\lab-pc-01.local.yaml
```

Then, if needed:

```powershell
daq board sysmon dev1 --profile .\profiles\lab-pc-01.local.yaml
daq acquire multi two_board --decode-json --profile .\profiles\lab-pc-01.local.yaml
```

## Troubleshooting

If installation works but hardware commands fail:

- check board and TCM IP addresses
- check network access to the DAQ hardware
- verify the selected profile path is the one you edited

If you need a development install instead of a release install, use:

```powershell
python -m pip install -e .
```
