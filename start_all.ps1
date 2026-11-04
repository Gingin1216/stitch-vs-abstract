#Requires -Version 5.1
<#
.SYNOPSIS
  崩坏缝合局（Stitch vs. Abstract）一键启动脚本（Windows / PowerShell 5.1+）

.DESCRIPTION
  启动三个后端服务 + 前端开发服务器：
    semantic  : http://127.0.0.1:8003  （语义评估）
    agents    : http://127.0.0.1:8002  （Agent 层，默认真实 LLM 模式）
    engine    : http://127.0.0.1:8001  （游戏引擎）
    frontend  : http://localhost:5173 （前端，VITE_API_MODE=remote，代理到 engine）

  使用前提：只需把根目录 .env 配好（没有就从 .env.example 复制一份，填上
  LLM_API_KEY / LLM_BASE_URL / LLM_MODEL），然后执行本脚本即可。

  特性：
    - 自动读取根目录 .env 并注入环境变量（三个服务用 os.getenv 读配置，不自动加载 .env）
    - 自动探测 PATH 中的 python 与 npm.cmd，不再绑定某台机器的绝对路径
      （如需指定，可在 .env 或当前会话设置 PYTHON_EXE / NPM_CMD）
    - 依赖缺失时自动执行 pip install / npm install（已安装则跳过）
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
$FrontendPort = 5173

$LogDir = Join-Path $Root "logs"
$EnvFile = Join-Path $Root ".env"
$EnvExample = Join-Path $Root ".env.example"

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
                # 兼容 .env 里习惯性写成 KEY="value" 的引号包裹
                if ($v.Length -ge 2 -and $v.StartsWith('"') -and $v.EndsWith('"')) {
                    $v = $v.Substring(1, $v.Length - 2)
                }
                Set-Item -Path "env:$k" -Value $v
            }
        }
}

function Resolve-Executable([string]$OverrideEnv, [string]$CommandName, [string]$Hint) {
    if (Test-Path Env:$OverrideEnv) {
        $p = (Get-Item -Path "Env:$OverrideEnv").Value
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
        throw "环境变量 $OverrideEnv 指向的路径不存在: $p"
    }
    $cmd = Get-Command $CommandName -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cmd) { throw "找不到 $CommandName，请先安装并加入 PATH（$Hint）" }
    return $cmd.Source
}

function Ensure-Dependencies {
    Write-Host ">> 检查依赖" -ForegroundColor Cyan
    & $PythonExe -c "import fastapi, uvicorn, openai, httpx, numpy, pydantic" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   缺少 Python 依赖，执行 pip install -r requirements.txt ..."
        & $PythonExe -m pip install -r (Join-Path $Root "requirements.txt")
        if ($LASTEXITCODE -ne 0) { throw "Python 依赖安装失败，请检查网络或 Python 环境" }
    } else {
        Write-Host "   Python 依赖已就绪"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Root "frontend\node_modules"))) {
        Write-Host "   缺少前端依赖，执行 npm install ..."
        Push-Location (Join-Path $Root "frontend")
        try {
            & $NpmCmd install
            if ($LASTEXITCODE -ne 0) { throw "npm install 失败，请检查网络或 Node 环境" }
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "   前端依赖已就绪"
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

# ---------------- 0. 校验 .env ----------------
if (-not (Test-Path -LiteralPath $EnvFile)) {
    if (Test-Path -LiteralPath $EnvExample) {
        Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
        throw "未找到 .env，已从 .env.example 生成。请填写 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 后重跑本脚本。"
    }
    throw "找不到 .env，也没有 .env.example，无法启动"
}

Write-Host ">> 加载 .env 环境变量" -ForegroundColor Cyan
Load-EnvFile

if (-not $env:LLM_API_KEY -or $env:LLM_API_KEY.Trim() -match '^sk-x{3,}$|^none$|^your') {
    Write-Warning "   .env 中 LLM_API_KEY 为空或仍是占位值，agents 将以真实模式启动但调用会失败（请先配置 Key）"
}
if ($env:MOCK -eq "1") {
    Write-Warning "   .env 中 MOCK=1，agents 将返回写死数据而不是真实 LLM"
}

# ---------------- 1. 探测可执行文件 ----------------
Write-Host ">> 探测 python / npm" -ForegroundColor Cyan
$PythonExe = Resolve-Executable -OverrideEnv "PYTHON_EXE" -CommandName "python" -Hint "https://www.python.org/downloads/"
$NpmCmd = Resolve-Executable -OverrideEnv "NPM_CMD" -CommandName "npm.cmd" -Hint "https://nodejs.org/"
Write-Host "   python: $PythonExe"
Write-Host "   npm   : $NpmCmd"

Ensure-Dependencies

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

$Backends = @(
    @{ Name = "semantic"; Port = 8003; Dir = (Join-Path $Root "semantic")
       Out = (Join-Path $LogDir "semantic.log");     Err = (Join-Path $LogDir "semantic.err.log") },
    @{ Name = "agents";   Port = 8002; Dir = (Join-Path $Root "agents")
       Out = (Join-Path $LogDir "agents.log");       Err = (Join-Path $LogDir "agents.err.log") },
    @{ Name = "engine";   Port = 8001; Dir = (Join-Path $Root "engine")
       Out = (Join-Path $LogDir "engine.log");       Err = (Join-Path $LogDir "engine.err.log") }
)

# ---------------- 2. 后端三服务 ----------------
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

# ---------------- 3. 前端（可选） ----------------
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
            Write-Host "   端口 $($FrontendPort) 已被占用 ($names)，跳过。如需强制重启加 -Restart"
        }
    }
    if (-not (Get-ListeningPids $FrontendPort)) {
        $fOut = Join-Path $LogDir "frontend.log"
        $fErr = Join-Path $LogDir "frontend.err.log"
        # PowerShell 5.1 的 Start-Process 没有 -Environment 参数，改为先设置再启动（子进程继承）
        $previousApiMode = $env:VITE_API_MODE
        $env:VITE_API_MODE = "remote"
        try {
            $p = Start-Process -FilePath $NpmCmd `
                -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1") `
                -WorkingDirectory (Join-Path $Root "frontend") -WindowStyle Hidden `
                -RedirectStandardOutput $fOut -RedirectStandardError $fErr -PassThru
        } finally {
            if ($null -eq $previousApiMode) {
                Remove-Item Env:VITE_API_MODE -ErrorAction SilentlyContinue
            } else {
                $env:VITE_API_MODE = $previousApiMode
            }
        }
        Write-Host "   已启动 PID=$($p.Id)，日志: $fOut"
        $FrontendStarted = $true
    }
}

# ---------------- 4. 等待就绪并验证 ----------------
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

# ---------------- 5. 汇总 ----------------
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
