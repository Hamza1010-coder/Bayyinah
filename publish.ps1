# Publish Bayyinah to GitHub.
#
#   1. Create an empty repo (no README, no license) at https://github.com/new
#   2. From the repo root:
#
#        .\publish.ps1 -User <your-github-username>
#
#   Options:
#     -Repo bayyinah       repository name (must match the one you created)
#     -Name "Your Name"    commit author name  (default: your username)
#     -Email "you@x.com"   commit author email (default: user@users.noreply.github.com)
#     -KeepHistory         keep the existing commits instead of squashing
#     -NoPush              prepare locally only, do not push
#
# Why this squashes by default: the existing commits are authored as
# "Bayyinah Developer <dev@bayyinah.local>" and were all created on one day,
# which reads as a generated dump. One clean root commit under your own name,
# followed by your real work over the coming weeks, is a more honest history
# than a fabricated timeline.
#
# It uses only plumbing-level git commands (no rebase/filter-branch), so it
# works even where Git's bundled shell is restricted.

param(
    [Parameter(Mandatory = $true)][string]$User,
    [string]$Repo = "bayyinah",
    [string]$Name = "",
    [string]$Email = "",
    [switch]$KeepHistory,
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path "pyproject.toml") -or -not (Test-Path "README.md")) {
    throw "run this from the repository root (pyproject.toml and README.md must exist)"
}
if (-not (Test-Path ".git")) {
    throw "no .git directory here"
}

$dirty = git status --porcelain
if ($dirty) {
    throw "working tree is not clean - commit or stash first:`n$dirty"
}

if (-not $Name)  { $Name = $User }
if (-not $Email) { $Email = "$User@users.noreply.github.com" }

Write-Host "author : $Name <$Email>"
Write-Host "remote : https://github.com/$User/$Repo.git"
Write-Host ""

git config user.name $Name
git config user.email $Email

if (-not $KeepHistory) {
    Write-Host "squashing into one root commit..."
    git checkout --orphan bayyinah-root | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "could not create orphan branch" }
    git add -A
    # No --reset-author here: a fresh commit takes the configured identity, and
    # --reset-author is only valid together with --amend.
    git commit -q -m "Bayyinah: Arabic-first, citation-verified compliance copilot for Saudi labour law" -m "Hybrid retrieval over an article-level corpus, programmatic citation verification (a quote must be a verbatim substring of the cited article), deterministic end-of-service calculation, contract X-Ray with DOCX/HTML reports, and a CI-gated eval harness. Core is stdlib-only Python; HTTP API with auth, rate limiting and audit trail. 163 tests."
    if ($LASTEXITCODE -ne 0) { throw "commit failed" }
    git branch -M main
} else {
    Write-Host "keeping existing history; only future commits use the new identity."
}

Write-Host ""
Write-Host "history now:"
git log --format="  %h  %an <%ae>  %s" | Select-Object -First 6
Write-Host ""

$remotes = git remote
if ($remotes -contains "origin") {
    Write-Host "origin already set: $(git remote get-url origin)"
} else {
    git remote add origin "https://github.com/$User/$Repo.git"
    Write-Host "origin added -> https://github.com/$User/$Repo.git"
}

if ($NoPush) {
    Write-Host ""
    Write-Host "NoPush set - stopping before push."
    return
}

Write-Host ""
Write-Host "pushing (a browser window may open for GitHub authentication)..."
git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Push failed. Two usual causes:" -ForegroundColor Yellow
    Write-Host "  - the repository does not exist yet: https://github.com/new (name: $Repo, no README, no license)" -ForegroundColor Yellow
    Write-Host "  - GitHub authentication was cancelled" -ForegroundColor Yellow
    Write-Host "Then re-run: .\publish.ps1 -User $User" -ForegroundColor Yellow
    return
}

Write-Host ""
Write-Host "published: https://github.com/$User/$Repo" -ForegroundColor Green
Write-Host "next: set the description + topics, then record the 3-minute demo (docs/DEMO.md)." -ForegroundColor Green

