@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Backup-EduScan.ps1"
if errorlevel 1 pause
