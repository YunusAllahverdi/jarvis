# Jarvis'i tek adresten sunar: kabuğu derler, sonra backend'i başlatır.
#
# Kullanım senaryosu: bilgisayar açık kalıyor, Jarvis tabletten kullanılıyor.
# Tablet iki ayrı sunucuya bağlanamaz, bu yüzden kabuk derlenip backend'e
# verilir ve ortada TEK bir adres olur.
#
#   .\scripts\serve.ps1                  # yalnızca bu bilgisayardan
#   .\scripts\serve.ps1 -Network         # ağdaki cihazlardan (tablet)
#
# -Network verildiğinde sunucu 0.0.0.0'a bağlanır ve JARVIS_API_TOKEN
# ZORUNLU olur; tanımlı değilse script başlamadan durur. Bu bilinçlidir:
# anahtarsız ağa açılan bir Jarvis, kullanıcının belleğini, dosyalarını ve
# terminalini aynı ağdaki herkese açar.

param(
    [switch]$Network,
    [int]$Port = 8000,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# --- kimlik kontrolü ------------------------------------------------------

$bindHost = if ($Network) { "0.0.0.0" } else { "127.0.0.1" }

if ($Network) {
    $token = $env:JARVIS_API_TOKEN
    if (-not $token -and (Test-Path ".env")) {
        # .env'den oku; script ortam değişkenlerini kendisi yüklemez ama
        # kullanıcıya "anahtar yok" demeden önce oraya bakması doğrudur.
        $line = Select-String -Path ".env" -Pattern '^\s*JARVIS_API_TOKEN\s*=\s*(.+)$' |
                Select-Object -First 1
        if ($line) { $token = $line.Matches[0].Groups[1].Value.Trim() }
    }

    if (-not $token) {
        Write-Host ""
        Write-Host "  Ağa açmak için bir anahtar gerekiyor." -ForegroundColor Yellow
        Write-Host "  .env dosyanıza şunu ekleyin:" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "      JARVIS_API_TOKEN=$([guid]::NewGuid().ToString('N'))" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  Anahtarsız ağa açılan bir Jarvis, belleğinizi ve" -ForegroundColor Yellow
        Write-Host "  dosyalarınızı aynı ağdaki herkese açar." -ForegroundColor Yellow
        Write-Host ""
        exit 1
    }
}

# --- kabuğu derle ---------------------------------------------------------

if (-not $SkipBuild) {
    Write-Host "Kabuk derleniyor..." -ForegroundColor DarkGray
    npm run build --prefix frontend
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# --- adresi göster --------------------------------------------------------

Write-Host ""
Write-Host "  Jarvis hazır." -ForegroundColor Green
Write-Host "  Bu bilgisayardan:  http://127.0.0.1:$Port"

if ($Network) {
    # Tabletin gireceği adres. Birden fazla arayüz olabilir; hepsi listelenir
    # ve kullanıcı tabletle aynı ağda olanı seçer.
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        ForEach-Object { Write-Host "  Tabletten:         http://$($_.IPAddress):$Port" }
    Write-Host ""
    Write-Host "  Tablette anahtar bir kez sorulacak." -ForegroundColor DarkGray
}
Write-Host ""

# --- başlat ---------------------------------------------------------------

$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $python -m uvicorn app.main:app --host $bindHost --port $Port
