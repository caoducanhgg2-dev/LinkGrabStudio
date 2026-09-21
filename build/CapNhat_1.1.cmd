@echo off
setlocal
title Cap nhat LinkGrab Studio
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Apply_Update_1.1.ps1" -InstallDir "%~1"
if errorlevel 1 (
  echo.
  echo Cap nhat khong thanh cong. Ban cu van duoc giu nguyen.
  pause
)
endlocal
