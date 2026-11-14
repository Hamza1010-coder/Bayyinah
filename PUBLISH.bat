@echo off
setlocal
cd /d "%~dp0"

echo.
echo   ==============================================
echo    Bayyinah  ->  GitHub
echo   ==============================================
echo.

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo [X] This folder is not a git repository.
  echo     Run this file from D:\Projects\bayyinah
  echo.
  pause
  exit /b 1
)

echo [1/6] Setting the commit author...
git config user.name "Hamza Yousaf"
git config user.email "190218119+Hamza1010-coder@users.noreply.github.com"

echo [2/6] Preparing a clean single commit...
git rev-parse --verify bayyinah-root >nul 2>&1
if errorlevel 1 (
  git checkout --orphan bayyinah-root
  git add -A
  git commit -m "Bayyinah: Arabic-first, citation-verified compliance copilot for Saudi labour law" -m "Hybrid retrieval over an article-level corpus, programmatic citation verification (a quote must be a verbatim substring of the cited article), deterministic end-of-service calculation, contract X-Ray with DOCX/HTML reports, and a CI-gated eval harness. 163 tests."
  git branch -M main
) else (
  echo       already prepared, skipping
)

echo [3/6] Connecting to GitHub...
git remote remove origin >nul 2>&1
git remote add origin https://github.com/Hamza1010-coder/bayyinah.git

echo [4/6] Pushing...
echo       A browser window may open. Sign in and click Authorize.
echo.
git push -u origin main

if errorlevel 1 (
  echo.
  echo [X] Push failed.
  echo.
  echo   Most likely: the repository does not exist yet.
  echo   Create it first:  https://github.com/new
  echo     name: bayyinah   visibility: Public   no README, no license
  echo   Then double-click this file again.
  echo.
  pause
  exit /b 1
)

echo.
echo   ==============================================
echo    PUBLISHED
echo    https://github.com/Hamza1010-coder/bayyinah
echo   ==============================================
echo.
echo   Next: add the description + topics on the repo page,
echo         then pin it on your profile.
echo.
pause
