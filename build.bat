@echo off
setlocal
echo =======================================================
echo  Building yt-dlp-tui Standalone Executable (.exe)
echo =======================================================

echo.
echo [1/3] Checking dependencies...
python -m pip install -r requirements.txt

echo.
echo [2/3] Building executable with PyInstaller...
python -m PyInstaller --noconfirm --clean yt-dlp-tui.spec

echo.
if exist "dist\yt-dlp-tui.exe" (
    echo [3/3] BUILD SUCCESSFUL!
    echo Standalone executable created at: dist\yt-dlp-tui.exe
) else (
    echo [3/3] BUILD FAILED! Check error output above.
)
echo =======================================================
endlocal
