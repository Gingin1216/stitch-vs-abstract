#Requires -Version 7.0
<#
.SYNOPSIS
  崩坏缝合局（Stitch vs. Abstract）一键启动脚本（Windows / PowerShell 7）

.DESCRIPTION
  启动三个后端服务 + 前端开发服务器：
    semantic  : http://127.0.0.1:8003  （语义评估）
    agents    : http://127.0.0.1:8002  （Agent 层，真实 LLM 模式）
    engine    : http://127.0.0.1:8001  （游戏引擎）
    frontend  : http://localhost:5173 （前端，VITE_API_MODE=remote，代理到 engine）

  特性：
    - 自动读取根目录 .env 并注入环境变量（三个服务用 os.getenv 读配置，不自动加载 .env）
    - 服务以独立进程启动（Start-Process），脚本退出后仍保持运行
    - 日志写入 logs\ 目录（semantic.log / agents.log / engine.log / frontend.log）
    - 端口已被占用时默认跳过；加 -Restart 会先停止占用进程再启动

.EXAMPLE
  .\start_all.ps1               # 启动全部（后端 + 前端）
  .\start_all.ps1 -NoFrontend   # 只启动后端三个服务
  .\start_all.ps1 -Restart      # 端口被占用时强制重启
#>
[CmdletBinding()]
param(
    [switch]$NoFrontend,
    [switch]$Restart
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

# ==================== 可配置项 ====================
# Python：若 python 命令被沙箱运行时劫持，必须用系统 Python 完整路径
$PythonExe = "C:\Users\nicole\AppData\Local\Programs\Python\Python313\python.exe"
# npm：npm.ps1 需要 pwsh 才能执行，Start-Process 直接调用 npm.cmd 更稳
$NpmCmd = "C:\Users\nicole\AppData\Local\Doubao\User Data\sandbox_runtime\bases\772984f6fd3a8ae0ae7d2422cd7c2bfa\node\npm.cmd"
$FrontendPort = 5173
# ==================================================

$LogDir = Join-Path $Root "logs"
$EnvFile = Join-Path $Root ".env"

if (-not (Test-Path -LiteralPath $PythonExe)) { throw "找不到 Python: $PythonExe" }
if (-not (Test-Path -LiteralPath $NpmCmd))    { throw "找不到 npm.cmd: $NpmCmd" }
if (-not (Test-Path -LiteralPath $EnvFile))   { throw "找不到 .env: $EnvFile" }
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

$Backends = @(
    @{ Name = "semantic"; Port = 8003; Dir = (Join-Path $Root "semantic")
       Out = (Join-Path $LogDir "semantic.log");     Err = (Join-Path $LogDir "semantic.err.log") },
    @{ Name = "agents";   Port = 8002; Dir = (Join-Path $Root "agents")
       Out = (Join-Path $LogDir "agents.log");       Err = (Join-Path $LogDir "agents.err.log") },
    @{ Name = "engine";   Port = 8001; Dir = (Join-Path $Root "engine")
       Out = (Join-Path $LogDir "engine.log");       Err = (Join-Path $LogDir "engine.err.log") }
)

# ---------------- 工具函数 ----------------
function Load-EnvFile {
    Get-Content -LiteralPath $EnvFile -Encoding UTF8 |
        Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' } |
        ForEach-Object {
            $line = ($_ -replace '\s*#.*$', '').Trim()
            $idx = $line.IndexOf('=')
            if ($idx -gt 0) {
                $k = $line.Substring(0, $idx).Trim()
                $v = $line.Substring($idx + 1).Trim()
                Set-Item -Path "env:$k" -Value $v
            }
        }
}

function Get-ListeningPids([int]$Port) {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
}

function Wait-Port([int]$Port, [int]$TimeoutSec = 30) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Stop-PortOwners([int]$Port) {
    $pids = Get-ListeningPids $Port
    foreach ($pid_ in $pids) {
        $pr = Get-Process -Id $pid_ -ErrorAction SilentlyContinue
        Write-Host "   停止占用进程: $(if ($pr) { "PID $pid_ ($($pr.ProcessName))" } else { "PID $pid_" })"
        Stop-Process -Id $pid_ -Force -ErrorAction SilentlyContinue
    }
    if ($pids) { Start-Sleep -Seconds 2 }
}

# ---------------- 0. 加载 .env ----------------
Write-Host ">> 加载 .env 环境变量" -ForegroundColor Cyan
Load-EnvFile

# ---------------- 1. 后端三服务 ----------------
foreach ($s in $Backends) {
    Write-Host ">> $($s.Name) (port $($s.Port))" -ForegroundColor Cyan
    $pids = Get-ListeningPids $s.Port
    if ($pids) {
        if ($Restart) {
            Stop-PortOwners $s.Port
        } else {
            $names = ($pids | ForEach-Object {
                $pr = Get-Process -Id $_ -ErrorAction SilentlyContinue
                if ($pr) { "PID $_ ($($pr.ProcessName))" } else { "PID $_" }
            }) -join ", "
            Write-Host "   端口 $($s.Port) 已被占用 ($names)，跳过。如需强制重启加 -Restart"
            continue
        }
    }
    $p = Start-Process -FilePath $PythonExe `
        -ArgumentList @("-m", "uvicorn", "main:app", "--port", "$($s.Port)") `
        -WorkingDirectory $s.Dir -WindowStyle Hidden `
        -RedirectStandardOutput $s.Out -RedirectStandardError $s.Err -PassThru
    Write-Host "   已启动 PID=$($p.Id)，日志: $($s.Out)"
}

# ---------------- 2. 前端（可选） ----------------
$FrontendStarted = $false
if (-not $NoFrontend) {
    Write-Host ">> frontend (port $FrontendPort, VITE_API_MODE=remote)" -ForegroundColor Cyan
    $fPids = Get-ListeningPids $FrontendPort
    if ($fPids) {
        if ($Restart) {
            Stop-PortOwners $FrontendPort
        } else {
            $names = ($fPids | ForEach-Object {
                $pr = Get-Process -Id $_ -ErrorAction SilentlyContinue
                if ($pr) { "PID $_ ($($pr.ProcessName))" } else { "PID $_" }
            }) -join ", "
            Write-Host "   端口 $FrontendPort 已被占用 ($names)，跳过。如需强制重启加 -Restart"
        }
    }
    if (-not (Get-ListeningPids $FrontendPort)) {
        $fOut = Join-Path $LogDir "frontend.log"
        $fErr = Join-Path $LogDir "frontend.err.log"
        $p = Start-Process -FilePath $NpmCmd `
            -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1") `
            -WorkingDirectory (Join-Path $Root "frontend") -WindowStyle Hidden `
            -Environment @{ VITE_API_MODE = "remote" } `
            -RedirectStandardOutput $fOut -RedirectStandardError $fErr -PassThru
        Write-Host "   已启动 PID=$($p.Id)，日志: $fOut"
        $FrontendStarted = $true
    }
}

# ---------------- 3. 等待就绪并验证 ----------------
Write-Host "`n>> 等待服务就绪 ..." -ForegroundColor Cyan
foreach ($s in $Backends) {
    if (Wait-Port $s.Port 30) { Write-Host "   [$($s.Name)] 端口 $($s.Port) 就绪" }
    else { Write-Warning "   [$($s.Name)] 30s 内未就绪，请查看日志: $($s.Out)" }
}
if ($FrontendStarted) {
    if (Wait-Port $FrontendPort 30) { Write-Host "   [frontend] 端口 $FrontendPort 就绪" }
    else { Write-Warning "   [frontend] 30s 内未就绪，请查看日志: $(Join-Path $LogDir 'frontend.log')" }
}

# agents 健康检查（确认非 MOCK、模型配置生效）
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:8002/agents/health" -TimeoutSec 10
    if ($h.mock) { Write-Warning "   agents 处于 MOCK 模式（mock=true），如需真实 LLM 请检查环境变量后重启" }
    else { Write-Host "   agents: mock=$($h.mock), model=$($h.model) / strong=$($h.model_strong)" }
} catch {
    Write-Warning "   agents 健康检查失败: $($_.Exception.Message)"
}

# ---------------- 4. 汇总 ----------------
Write-Host "`n===== 启动完成 =====" -ForegroundColor Green
Write-Host "  engine    : http://localhost:8001   (游戏引擎)"
Write-Host "  agents    : http://localhost:8002   (Agent 层)"
Write-Host "  semantic  : http://localhost:8003   (语义评估)"
if ($FrontendStarted) {
    Write-Host "  frontend  : http://localhost:5173  (前端，remote 模式)" -ForegroundColor Yellow
    Write-Host "`n浏览器打开 http://localhost:5173 开始游戏（真实 LLM 模式，开局约等 20~30 秒）" -ForegroundColor Yellow
} else {
    Write-Host "  前端未启动（-NoFrontend 或端口已占用）"
}
Write-Host "`n日志目录: $LogDir"
Write-Host '停止服务: Get-NetTCPConnection -LocalPort 8001,8002,8003,5173 | ForEach-Object { Stop-Process -Id $($_.OwningProcess) -Force }'
