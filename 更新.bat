@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   ================================
echo   食亨智慧运营 — 更新中...
echo   ================================
echo.
git pull origin feature/watch-mode
call 安装.bat
echo.
echo   ✅ 更新完成！
echo.
pause
