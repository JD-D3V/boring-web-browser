@echo off
rem Build just the browser, with the Visual Studio environment in place.
rem Usage: build_chrome.bat [extra ninja arguments]
rem Only ever run one of these at a time against the build tree.
rem
rem BORING_SRC picks the tree. It defaults to the one that has always
rem been built here, so an existing habit keeps working; an engine
rem upgrade sets it to the new tree rather than editing this file.
setlocal
if "%BORING_SRC%"=="" set BORING_SRC=E:\ung\build\src
rem A stripped PATH loses vswhere, which vcvars64 shells out to.
set PATH=C:\Program Files (x86)\Microsoft Visual Studio\Installer;C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem;%PATH%
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
set TMP=E:\tmp
set TEMP=E:\tmp
set DEPOT_TOOLS_WIN_TOOLCHAIN=0
set PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%
cd /d %BORING_SRC%
rem Use the ninja inside the tree. A newer ninja on PATH deletes the tree's
rem .ninja_log and forces a full rebuild. ninja_guard.py picks the right
rem one and refuses if the log version would clash.
set BORING_NINJA=
for /f "delims=" %%N in ('python "%~dp0ninja_guard.py" out\Default') do set BORING_NINJA=%%N
if "%BORING_NINJA%"=="" (
  echo build_chrome: no ninja chosen, not building.
  exit /b 1
)
"%BORING_NINJA%" -C out\Default %* chrome chromedriver
exit /b %ERRORLEVEL%
