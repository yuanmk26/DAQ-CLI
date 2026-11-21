@echo off
setlocal
set "PROJECT=%~dp0.."
set "PYTHONPATH=%PROJECT%\src;%PYTHONPATH%"
set "QT_PYTHON=%PROJECT%\.venv-qt\Scripts\python.exe"
if not exist "%QT_PYTHON%" set "QT_PYTHON=python"
if "%~1"=="" (
    pushd "%PROJECT%"
    "%QT_PYTHON%" -m daq_cli.qt_replay
    if errorlevel 1 goto failed
    popd
) else (
    "%QT_PYTHON%" -m daq_cli.qt_replay %*
)
if not errorlevel 1 exit /b 0
:failed
pause
exit /b 1
