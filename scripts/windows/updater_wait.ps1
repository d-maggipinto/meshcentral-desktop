# SPDX-License-Identifier: Apache-2.0
# Windows CI: wait for the in-app upgrade helper to finish: the downloaded installer copy is deleted and the
# app was started again from its installed location. Then close that app. Exit code 0 = upgrade hand-over OK.
param([Parameter(Mandatory)][string]$Exe, [Parameter(Mandatory)][string]$CopyListFile, [int]$Timeout = 300)
$copy = (Get-Content $CopyListFile -Raw).Trim()
$t = Get-Date
do {
  Start-Sleep -Seconds 2
  $p = Get-Process MeshCentralDesktop -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $Exe }
  $done = (-not (Test-Path -LiteralPath $copy)) -and $p
} until ($done -or ((Get-Date) - $t).TotalSeconds -gt $Timeout)
"installer copy removed: $(-not (Test-Path -LiteralPath $copy))"
"app restarted from $Exe : $([bool]$p)"
$p | Stop-Process -Force -ErrorAction SilentlyContinue
if ($done) { exit 0 } else { exit 1 }
