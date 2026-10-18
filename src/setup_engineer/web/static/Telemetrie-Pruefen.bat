<# : Batch-Teil - startet den PowerShell-Teil weiter unten
@echo off
title Setup-Engineer: Telemetrie pruefen
powershell -NoProfile -ExecutionPolicy Bypass -Command "$f=[IO.File]::ReadAllText('%~f0'); Invoke-Expression $f"
echo.
pause
exit /b
#>
# ---------------------------------------------------------------------------------------------
# Setup-Engineer: findet GT3- und GTP-Telemetrie mit genug Runden und kopiert sie auf Wunsch
# in einen eigenen Ordner. Liest nur - aendert, loescht oder verschickt nichts.
# ---------------------------------------------------------------------------------------------
$ErrorActionPreference = 'Stop'
$MinLaps = 7
$GtpMarkers = @('gtp', 'arx-06', 'm hybrid v8', 'v-series.r', '963', '499p')

function Get-CarClass([string]$name) {
    $n = $name.ToLower()
    foreach ($m in $GtpMarkers) { if ($n.Contains($m)) { return 'GTP' } }
    if ($n.Contains('gt3') -and -not $n.Contains('cup')) { return 'GT3' }
    return $null
}

function Read-Ibt([string]$path) {
    $fs = [IO.File]::Open($path, 'Open', 'Read', 'ReadWrite')
    try {
        $br = New-Object IO.BinaryReader($fs)
        $head = $br.ReadBytes(144)
        if ($head.Length -lt 144) { return $null }
        $len = [BitConverter]::ToInt32($head, 16)
        $off = [BitConverter]::ToInt32($head, 20)
        $laps = [BitConverter]::ToInt32($head, 136)
        if ($off -le 0 -or $len -le 0 -or ($off + $len) -gt $fs.Length) { return $null }
        $fs.Position = $off
        $yaml = [Text.Encoding]::GetEncoding(28591).GetString($br.ReadBytes($len))
    } finally { $fs.Close() }
    $car = '?'
    $m = [regex]::Match($yaml, 'DriverCarIdx:\s*(\d+)')
    if ($m.Success) {
        $idx = $m.Groups[1].Value
        foreach ($part in ([regex]::Split($yaml, '\n\s*- CarIdx:\s*') | Select-Object -Skip 1)) {
            if ($part -match "^$idx\r?\n") {
                $c = [regex]::Match($part, 'CarScreenName:\s*(.+)')
                if ($c.Success) { $car = $c.Groups[1].Value.Trim() }
                break
            }
        }
    }
    $t = [regex]::Match($yaml, 'TrackDisplayName:\s*(.+)')
    $track = if ($t.Success) { $t.Groups[1].Value.Trim() } else { '?' }
    return [pscustomobject]@{ Car = $car; Track = $track; Laps = $laps }
}

$docs = [Environment]::GetFolderPath('MyDocuments')
$dir = Join-Path $docs 'iRacing\telemetry'
Write-Host ''
Write-Host '=== Setup-Engineer: Telemetrie pruefen ===' -ForegroundColor Yellow
Write-Host ''
if (-not (Test-Path $dir)) {
    Write-Host "Der Ordner $dir wurde nicht gefunden."
    $dir = Read-Host 'Pfad zum Telemetrie-Ordner eingeben (oder leer lassen zum Beenden)'
    if (-not $dir -or -not (Test-Path $dir)) { return }
}
$target = Join-Path $dir 'Setup-Engineer-Upload'
$files = @(Get-ChildItem -Path $dir -Filter *.ibt -File -Recurse | Where-Object { $_.DirectoryName -ne $target })
Write-Host "Durchsuche $($files.Count) Dateien in $dir ..."
$good = @()
$skip = @{}
$i = 0
foreach ($f in $files) {
    $i++
    Write-Progress -Activity 'Pruefe Telemetrie' -Status $f.Name -PercentComplete ($i * 100 / [Math]::Max(1, $files.Count))
    try { $info = Read-Ibt $f.FullName } catch { $info = $null }
    if ($null -eq $info) { $skip['nicht lesbar']++; continue }
    $cls = Get-CarClass $info.Car
    if (-not $cls) { $skip['kein GT3/GTP']++; continue }
    if ($info.Laps -lt $MinLaps) { $skip['zu wenige Runden']++; continue }
    $good += [pscustomobject]@{ Datei = $f.Name; Klasse = $cls; Auto = $info.Car; Strecke = $info.Track; Runden = $info.Laps
                                MB = [Math]::Round($f.Length / 1MB); Datum = $f.LastWriteTime.ToString('dd.MM.yyyy'); Pfad = $f.FullName }
}
Write-Progress -Activity 'Pruefe Telemetrie' -Completed
Write-Host ''
if ($good.Count -eq 0) {
    Write-Host 'Keine passenden Dateien gefunden (GT3 oder GTP mit mindestens 7 Runden).'
} else {
    $good | Sort-Object Klasse, Auto, Datum | Format-Table Datum, Klasse, Auto, Strecke, Runden, MB, Datei -AutoSize | Out-String -Width 220 | Write-Host
    $sum = ($good | Measure-Object MB -Sum).Sum
    Write-Host ("{0} von {1} Dateien sind fuer uns interessant ({2} MB)." -f $good.Count, $files.Count, $sum) -ForegroundColor Green
}
foreach ($k in $skip.Keys) { Write-Host ("  nicht passend: {0} x {1}" -f $skip[$k], $k) -ForegroundColor DarkGray }
if ($good.Count -eq 0) { return }
Write-Host ''
$a = Read-Host "In den Ordner $target kopieren? (J/N)"
if ($a -notmatch '^[jJyY]') { Write-Host 'Nichts kopiert.'; return }
New-Item -ItemType Directory -Force -Path $target | Out-Null
$n = 0
foreach ($g in $good) {
    $dest = Join-Path $target $g.Datei
    if (-not (Test-Path $dest)) { Copy-Item -LiteralPath $g.Pfad -Destination $dest; $n++ }
}
Write-Host "$n Dateien kopiert. Jetzt im Portal unter 'Altdaten hochladen' diesen Ordner waehlen." -ForegroundColor Green
Start-Process explorer.exe $target
