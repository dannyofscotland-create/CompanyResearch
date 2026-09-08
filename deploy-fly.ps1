# Run this in PowerShell AFTER: flyctl auth login
# Creates the always-on app, volume, secret, and deploys.

$ErrorActionPreference = "Stop"
$env:Path = "C:\Users\dan21\.fly\bin;" + $env:Path
Set-Location $PSScriptRoot

if (-not $env:ACCESS_CODE) {
  $env:ACCESS_CODE = Read-Host "Pick a private access code for your phone (not a bank password)"
}
if (-not $env:ACCESS_CODE) {
  throw "Access code required."
}

flyctl auth whoami
flyctl apps create companyresearch-desk --org personal 2>$null
flyctl volumes create cr_data --app companyresearch-desk --region lhr --size 1 --yes 2>$null
flyctl secrets set ACCESS_CODE="$env:ACCESS_CODE" --app companyresearch-desk
flyctl deploy --app companyresearch-desk --remote-only
flyctl status --app companyresearch-desk
Write-Host ""
Write-Host "Open that HTTPS URL on your phone. Unlock with your access code. Tick keep watching."
Write-Host "Your desk PC can then be turned off."
