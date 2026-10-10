@echo off
REM Starts the agent using the Python you already have installed.
REM Use this if you would rather not build the standalone .exe.
cd /d "%~dp0"
start "" pythonw run_agent.py
