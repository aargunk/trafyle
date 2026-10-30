@echo off
rem Trafyle kurulumu - cift tiklayin.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\kur.ps1"
if errorlevel 1 pause
