# SPDX-License-Identifier: Apache-2.0
# Authenticode signing for the Windows build. Inactive until the repository has the secrets
# WINDOWS_SIGN_PFX_BASE64 (the code-signing certificate, .pfx, base64) and WINDOWS_SIGN_PFX_PASSWORD.
# Usage: pwsh scripts/windows/sign.ps1 <file> [<file> ...]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Files)
if (-not $env:SIGN_PFX_BASE64) { "Code signing: no certificate configured, left unsigned: $($Files -join ', ')"; exit 0 }
$pfx = Join-Path $env:RUNNER_TEMP ("sign-" + [guid]::NewGuid() + ".pfx")
[IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:SIGN_PFX_BASE64))
try {
  $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" |
    Sort-Object FullName -Descending | Select-Object -First 1
  & $signtool.FullName sign /f $pfx /p $env:SIGN_PFX_PASSWORD /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
    /d "MeshCentral Desktop" /du "https://github.com/d-maggipinto/meshcentral-desktop" $Files
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
  & $signtool.FullName verify /pa $Files
  exit $LASTEXITCODE
} finally {
  Remove-Item $pfx -Force -ErrorAction SilentlyContinue
}
