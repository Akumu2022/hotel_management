# Local PostgreSQL (16 or 17) for development, without Docker or a Windows service.
#   .\scripts\dev-db.ps1 start   # first run creates the cluster and the hotel / hotel_test databases
#   .\scripts\dev-db.ps1 stop
#   .\scripts\dev-db.ps1 status
# Binaries: %LOCALAPPDATA%\pgsql16\bin or %LOCALAPPDATA%\pgsql17\bin (override with $env:PGBIN).
# Data:     backend\.pgdata (git-ignored). User/password: hotel / hotel, port 5432.
param([ValidateSet("start", "stop", "status")][string]$Action = "start")

$ErrorActionPreference = "Stop"
$bin = $env:PGBIN
if (-not $bin) {
    $bin = @("pgsql16", "pgsql17x", "pgsql17") |
        ForEach-Object { Join-Path $env:LOCALAPPDATA "$_\bin" } |
        Where-Object { Test-Path (Join-Path $_ "pg_ctl.exe") } |
        Select-Object -First 1
}
if (-not $bin -or -not (Test-Path (Join-Path $bin "pg_ctl.exe"))) {
    throw "PostgreSQL binaries not found. See README (Local development)."
}

$data = Join-Path $PSScriptRoot "..\.pgdata"
$log = Join-Path $data "server.log"

switch ($Action) {
    "start" {
        $fresh = -not (Test-Path (Join-Path $data "PG_VERSION"))
        if ($fresh) {
            $pw = New-TemporaryFile
            Set-Content -Path $pw -Value "hotel" -NoNewline
            & "$bin\initdb.exe" -D $data -U hotel --pwfile=$pw -E UTF8 --locale=C -A scram-sha-256 | Out-Null
            $code = $LASTEXITCODE
            Remove-Item $pw
            if ($code -ne 0) { throw "initdb failed (exit $code)" }
        }
        # Own hidden window: the server must not inherit this console, or callers that capture
        # output wait forever (and closing them would stop the database).
        $p = Start-Process "$bin\pg_ctl.exe" -ArgumentList "-D", "`"$data`"", "-l", "`"$log`"", "-o", "`"-p 5432`"", "-w", "start" -WindowStyle Hidden -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw "PostgreSQL did not start; see $log" }
        if ($fresh) {
            $env:PGPASSWORD = "hotel"
            & "$bin\createdb.exe" -h localhost -U hotel hotel
            & "$bin\createdb.exe" -h localhost -U hotel hotel_test
        }
        "PostgreSQL running on localhost:5432 (data: $data)"
    }
    "stop" { & "$bin\pg_ctl.exe" -D $data -w stop }
    "status" { & "$bin\pg_ctl.exe" -D $data status }
}
