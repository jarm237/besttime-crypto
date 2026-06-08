[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "   Khởi động BestTime Crypto Dashboard" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan

# Di chuyển đến thư mục gốc của project
Set-Location -Path $PSScriptRoot

$ApiProcess = $null
$WebProcess = $null
$BotProcess = $null

try {
    # 1. Khởi động API Server (FastAPI)
    Write-Host "[1/3] Khởi động API Server (Cổng 8000)..." -ForegroundColor Yellow
    $ApiProcess = Start-Process -FilePath "python" -ArgumentList "-m uvicorn api.server:app --host 0.0.0.0 --port 8000" -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 1

    # 2. Khởi động Web Dashboard (Vite/React)
    Write-Host "[2/3] Khởi động Web Dashboard (Cổng 3000)..." -ForegroundColor Yellow
    Set-Location -Path "web"
    $WebProcess = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev" -WindowStyle Hidden -PassThru
    Set-Location -Path ".."
    Start-Sleep -Seconds 1

    # 3. Khởi động Trading Bot (Python Core)
    Write-Host "[3/3] Khởi động Trading Bot..." -ForegroundColor Yellow
    $BotProcess = Start-Process -FilePath "python" -ArgumentList "main.py" -NoNewWindow -PassThru

    Write-Host "===========================================" -ForegroundColor Green
    Write-Host " Tất cả dịch vụ đã chạy thành công!" -ForegroundColor Green
    Write-Host " 👉 Web Dashboard: http://localhost:3000" -ForegroundColor Green
    Write-Host " 👉 API Server:    http://localhost:8000" -ForegroundColor Green
    Write-Host " Nhấn Ctrl+C để tắt hệ thống." -ForegroundColor Yellow
    Write-Host "===========================================" -ForegroundColor Green

    # Đợi tiến trình Trading Bot
    $BotProcess | Wait-Process
}
finally {
    Write-Host ""
    Write-Host "Đang tắt tất cả các dịch vụ..." -ForegroundColor Red
    if ($ApiProcess -and !$ApiProcess.HasExited) { Stop-Process -Id $ApiProcess.Id -Force }
    if ($WebProcess -and !$WebProcess.HasExited) { Stop-Process -Id $WebProcess.Id -Force }
    if ($BotProcess -and !$BotProcess.HasExited) { Stop-Process -Id $BotProcess.Id -Force }
}
