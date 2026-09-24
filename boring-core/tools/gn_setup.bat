@echo off
rem Write out/Default/args.gn, bootstrap gn, run gn gen and build bindgen,
rem for a tree prepared by stage_upstream.py.
rem
rem build.py does all of this as part of a run it also compiles from.
rem Staging a tree and building it are separate steps here, so this is
rem that middle piece on its own: the same two flag files concatenated
rem the same way, the same bootstrap and gen, and the same bindgen build
rem straight afterwards.
rem
rem Usage: set BORING_ROOT=E:\ung-153-47 && gn_setup.bat
rem
rem Careful: gn gen rewrites toolchain.ninja, and everything downstream
rem of it rebuilds. Do not run this against a tree that has just linked
rem unless the args really changed.
setlocal
if "%BORING_ROOT%"=="" set BORING_ROOT=E:\ung
set SRC=%BORING_ROOT%\build\src
set PATH=C:\Program Files (x86)\Microsoft Visual Studio\Installer;C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem;%PATH%
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
set TMP=E:\tmp
set TEMP=E:\tmp
set DEPOT_TOOLS_WIN_TOOLCHAIN=0
set PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%

if not exist "%SRC%\out\Default" mkdir "%SRC%\out\Default"
if not exist "%SRC%\out\Default\args.gn" (
  copy /b "%BORING_ROOT%\ungoogled-chromium\flags.gn" + "%BORING_ROOT%\flags.windows.gn" "%SRC%\out\Default\args.gn" >nul || exit /b 1
  echo wrote args.gn
) else (
  echo args.gn already there, left alone
)

cd /d %SRC%
if not exist "out\Default\gn.exe" (
  python3 tools\gn\bootstrap\bootstrap.py -o out\Default\gn.exe --skip-generate-buildfiles || exit /b 1
)
out\Default\gn.exe gen out\Default --fail-on-unused-args || exit /b 1

rem bindgen is built from source rather than downloaded, and a build
rem stops on it a long way in if it is missing. build.py does this here
rem too, straight after gn gen.
if not exist "third_party\rust-toolchain\bin\bindgen.exe" (
  python3 tools\rust\build_bindgen.py --skip-test || exit /b 1
)
echo GN_SETUP_OK
exit /b 0
