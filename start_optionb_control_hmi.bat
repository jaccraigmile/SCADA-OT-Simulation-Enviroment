@echo off
setlocal

cd /d "%~dp0" || (
    echo Failed to change to the project directory.
    pause
    exit /b 1
)

py -3 .\optionb_control_hmi.py --modbus-host 10.77.20.10 --modbus-port 502 --unit-id 1 --controller-api http://10.77.10.10:8082 --host 127.0.0.1 --port 8083

if errorlevel 1 (
    echo.
    echo The Option B operator HMI exited with an error.
    pause
)
