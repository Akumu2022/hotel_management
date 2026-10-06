# Builds the Chakula Till APK and copies it to where the website serves it.
#   .\build-apk.ps1                                  # empty server box
#   .\build-apk.ps1 -Server http://10.0.2.2:8000     # prefill (emulator)
#   .\build-apk.ps1 -Install                         # also adb install -r to a connected phone/emulator
param([string]$Server = "", [string]$Out = "", [switch]$Install)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $env:JAVA_HOME) {
    foreach ($p in "C:\Program Files\Android\Android Studio1\jbr", "C:\Program Files\Android\Android Studio\jbr") {
        if (Test-Path $p) { $env:JAVA_HOME = $p; break }
    }
}
if (-not $env:JAVA_HOME) { throw "Set JAVA_HOME to Android Studio's jbr folder." }

$args = @("assembleDebug", "-q")
if ($Server) { $args += "-PchakulaServer=$Server" }
& .\gradlew.bat @args --offline
if ($LASTEXITCODE -ne 0) {
    Write-Host "Offline build failed, retrying online..."
    & .\gradlew.bat @args
    if ($LASTEXITCODE -ne 0) { throw "Build failed." }
}

$apk = "app\build\outputs\apk\debug\app-debug.apk"
$dest = if ($Out) { $Out } else { "..\web\public\downloads\chakula-till.apk" }
Copy-Item $apk $dest -Force
Write-Host ("Done: {0} ({1:N1} MB)" -f (Resolve-Path $dest), ((Get-Item $dest).Length / 1MB))

if ($Install) {
    $adb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
    & $adb install -r $apk
}
