# Run this from the extracted Traject folder after reviewing the files.
# Requires Git and authenticated GitHub access (credential manager or gh auth login).
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$target = 'https://github.com/umangmittal24MAQ/AI-Customer-Growth-Intelligence-Recommendation-Platform.git'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is not installed or not on PATH.' }
if (-not (Test-Path '.git')) { git init -b main; if ($LASTEXITCODE -ne 0) { throw 'git init failed' } }
$existing = git remote get-url origin 2>$null
if ($LASTEXITCODE -ne 0) { git remote add origin $target }
elseif ($existing -ne $target) { throw "Unexpected origin remote: $existing. Not overwriting it." }
# The .gitignore excludes .env, databases, logs, virtualenv, and build output.
git add .
if ($LASTEXITCODE -ne 0) { throw 'git add failed' }
Write-Host 'Review the staged files for secrets before committing:'
git diff --cached --stat
Write-Host ''
Write-Host 'Check git status and git diff --cached before running the following commands:'
Write-Host 'git commit -m "Initialize Traject with IndiaAI-only Qwen integration"'
Write-Host 'git push -u origin main'
