@echo off
setlocal
set "PROJECT=%~dp0.."
set "PYTHONPATH=%PROJECT%\src;%PYTHONPATH%"
set "QT_PYTHON=%PROJECT%\.venv-qt\Scripts\python.exe"
if not exist "%QT_PYTHON%" set "QT_PYTHON=python"
if "%~1"=="" (
    "%QT_PYTHON%" -m daq_cli.qt_replay "%PROJECT%\samples\four_board_00001"
) else (
    "%QT_PYTHON%" -m daq_cli.qt_replay %*
)
if errorlevel 1 (
    pause
    exit /b 1
)
