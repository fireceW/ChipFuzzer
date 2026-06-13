@echo off
REM Synchronize the chipfuzz directory from a remote server to a local desktop.
REM Usage: double-click this file or run it from the command line.

echo Synchronizing chipfuzz from the remote server...
scp -r root@your-server-host:/root/ChipFuzzer/chipfuzz %USERPROFILE%\Desktop\

if %errorlevel% == 0 (
    echo.
    echo Synchronization succeeded.
    echo Files were updated under: %USERPROFILE%\Desktop\chipfuzz
) else (
    echo.
    echo Synchronization failed. Please check:
    echo   1. Network connectivity.
    echo   2. SSH key configuration.
    echo   3. Remote server address.
)

pause
