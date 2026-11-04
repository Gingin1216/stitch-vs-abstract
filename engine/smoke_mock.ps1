#requires -version 5.0
<#
.SYNOPSIS
    崩坏缝合局 · MOCK 模式全链路冒烟测试脚本（PowerShell）。

.DESCRIPTION
    通过 engine:8001 的契约 §4 接口驱动一局完整 pvp 对局到 FINISHED，
    验证 engine → agents(MOCK) → semantic 全链路可用。

    前提（本脚本不会代为启动，需用户提前手动启动好三个后端服务）：
      - semantic:  python -m uvicorn main:app --port 8003
      - agents:    MOCK=1 模式启动（python -m uvicorn main:app --port 8002）
      - engine:    python -m uvicorn main:app --port 8001

    依赖：已激活虚拟环境、已安装 httpie。
    用法：./smoke_mock.ps1
          如遇执行策略限制：powershell -ExecutionPolicy Bypass -File smoke_mock.ps1
#>

# 修复 PowerShell 5.1 对原生命令输出的解码：按 UTF-8 读取 httpie 的 stdout，
# 否则中文词卡/句子会按 GBK 解码成乱码，选词必然失败
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# http 命令非零退出不抛异常，状态码由我们自己从输出解析
$ErrorActionPreference = 'Continue'

$Engine   = 'http://localhost:8001'
$Agents   = 'http://localhost:8002'
$Semantic = 'http://localhost:8003'

function Write-Ok([string]$msg)   { Write-Host $msg -ForegroundColor Green }
function Write-Bad([string]$msg)  { Write-Host $msg -ForegroundColor Red }
function Write-Warn([string]$msg) { Write-Host $msg -ForegroundColor Yellow }

function Fail([string]$msg) {
    Write-Bad "【失败】$msg"
    exit 1
}

function Invoke-Api {
    <#
    统一封装 httpie 调用：--print=hb（小写 = 响应头与响应体）解析状态码与 JSON。
    注意 httpie 大小写语义：H/B 大写是「请求」，h/b 小写才是「响应」。
    返回 @{ Status = int（0 表示服务未响应）; Json = 解析后的对象（可能为 $null）; Text = 原始响应体 }。
    注意不传 2>&1：httpie 的错误信息走 stderr，混入 stdout 会污染 JSON 解析。
    #>
    param(
        [Parameter(Mandatory = $true)][ValidateSet('GET', 'POST')][string]$Method,
        [Parameter(Mandatory = $true)][string]$Url,
        [string[]]$Fields = @()          # httpie 字段参数，如 'role=A'、'word=秦始皇'
    )
    try {
        # --ignore-stdin：脚本环境下 stdin 非 TTY，httpie 否则会试图从 stdin 读请求体
        $lines = @( & http --ignore-stdin --check-status --print=hb $Method $Url @Fields | ForEach-Object { "$_" } )
    } catch {
        return @{ Status = 0; Json = $null; Text = "无法执行 http 命令：$($_.Exception.Message)" }
    }
    if ($lines.Count -eq 0) {
        return @{ Status = 0; Json = $null; Text = "无响应：服务未启动或端口不通（http 退出码 $LASTEXITCODE）" }
    }
    $status = 0
    $headerEnd = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^HTTP/\S+\s+(\d{3})\b') { $status = [int]$Matches[1] }
        if ($status -gt 0 -and $lines[$i] -eq '') { $headerEnd = $i; break }
    }
    if ($status -eq 0) {
        return @{ Status = 0; Json = $null; Text = ($lines -join "`n").Trim() }
    }
    $body = if ($headerEnd -ge 0 -and $headerEnd + 1 -lt $lines.Count) {
        ($lines[($headerEnd + 1)..($lines.Count - 1)] -join "`n").Trim()
    } else { '' }
    $json = $null
    if ($body.StartsWith('{') -or $body.StartsWith('[')) {
        try { $json = $body | ConvertFrom-Json } catch { $json = $null }
    }
    return @{ Status = $status; Json = $json; Text = $body }
}

function Show-Hand([array]$cards) {
    ($cards | ForEach-Object { "$($_.word)(lv$($_.level))" }) -join ' / '
}

# ---------- 前置预检：确认三个服务已由用户手动启动 ----------
Write-Host "`n== 预检：确认三个后端服务已就绪 ==" -ForegroundColor Cyan

$health = Invoke-Api GET "$Agents/agents/health"
if ($health.Status -ne 200) { Fail "Agent 层 :8002 未就绪（请先以 MOCK=1 启动 agents 服务）。$($health.Text)" }
if (-not $health.Json.mock) { Fail "Agent 层 :8002 已就绪但未处于 MOCK 模式（health.mock 不为 true）。" }
Write-Ok "  agents:8002    OK（MOCK 模式）"

$jump = Invoke-Api POST "$Semantic/semantic/jump" @('sentence=冒烟预检', 'word=预检')
if ($jump.Status -ne 200) { Fail "语义层 :8003 未就绪（请先启动 semantic 服务）。$($jump.Text)" }
Write-Ok "  semantic:8003  OK"

# ---------- ① 创建对局 ----------
Write-Host "`n== 创建 pvp 对局 ==" -ForegroundColor Cyan
$created = Invoke-Api POST "$Engine/api/game" @('mode=pvp')
if ($created.Status -ne 200 -or -not $created.Json) {
    Fail "创建对局失败：HTTP $($created.Status) $($created.Text)"
}

$gameId = $created.Json.game_id        # game_id 存变量，后续 URL 自动传递，无需手动复制
Write-Ok "  game_id   = $gameId"
Write-Ok ("  开局句   = " + $created.Json.sentence)
Write-Ok ("  初始手牌 = " + (Show-Hand $created.Json.cards))
Write-Ok ("  第 1 回合先手 = " + $created.Json.first)

# ---------- ③④⑤ 轮流选词，直到 FINISHED ----------
Write-Host "`n== 轮流选词（A=抽象派优先高等级搞崩坏；B=缝合派优先低等级求稳）==" -ForegroundColor Cyan

$resp = $created
$used = @{}          # 本局已用词（客户端记录，减少无谓请求；查重判定以服务端为准）
$turn = 0

while ($resp.Json.state -ne 'FINISHED') {
    if (++$turn -gt 30) { Fail "已出 30 手仍未 FINISHED，链路异常。" }

    $role  = $resp.Json.state.Substring(0, 1)         # A_TURN → A / B_TURN → B
    $cards = @($resp.Json.cards)

    # 自动选词：A 从高等级往低挑，B 从低等级往高挑；跳过本局已用词
    $ordered = if ($role -eq 'A') { $cards | Sort-Object level -Descending }
               else               { $cards | Sort-Object level }
    $word = $null
    foreach ($c in $ordered) {
        if (-not $used.ContainsKey($c.word)) { $word = $c.word; break }
    }
    if (-not $word) { Fail "第 $turn 手（$role）：手牌全部用完仍无法选词。" }

    $r = Invoke-Api POST "$Engine/api/game/$gameId/pick" @("role=$role", "word=$word")

    # ④ 语义查重拦截：自动换词重试，不计为失败
    if ($r.Status -eq 409 -and $r.Json -and $r.Json.error.code -eq 'WORD_DUPLICATE') {
        Write-Warn "  第 $turn 手 $role 出「$word」撞查重（$($r.Json.error.message)），自动换词重试"
        $used[$word] = $true
        continue
    }
    if ($r.Status -ne 200 -or -not $r.Json) {
        Fail "第 $turn 手 $role 出「$word」失败：HTTP $($r.Status) $($r.Text)"
    }

    $used[$word] = $true
    $resp = $r
    # ⑤ 每步打印：status / 轮到谁 / 当前可用手牌
    $next = if ($r.Json.state -eq 'FINISHED') { '对局结束' } else { "轮到 $($r.Json.state.Substring(0,1))" }
    Write-Ok ("  第 $turn 手 | $role 出「$word」| HTTP $($r.Status) | " +
              "state=$($r.Json.state) | $next | 崩坏度=$($r.Json.collapse)")
    Write-Ok ("    可用手牌：" + (Show-Hand $r.Json.cards))
}

# ---------- ⑥ 终局：打印战报 ----------
Write-Host "`n== 对局 FINISHED，拉取战报 ==" -ForegroundColor Cyan
$report = Invoke-Api GET "$Engine/api/game/$gameId/report"
if ($report.Status -ne 200 -or -not $report.Json) {
    Fail "拉取战报失败：HTTP $($report.Status) $($report.Text)"
}
Write-Ok ("  winner     = " + $report.Json.winner)
Write-Ok ("  verdict    = " + $report.Json.verdict)
Write-Ok ("  比分       = A:$($report.Json.score_a) / B:$($report.Json.score_b)")
Write-Ok ("  崩坏曲线   = " + ($report.Json.collapse_curve -join ' → '))
Write-Ok ("  final_story= " + $report.Json.final_story)
Write-Ok ("  commentary = " + $report.Json.commentary)

Write-Host ""
Write-Warn "提示：本脚本只做冒烟验证，不会自动启动三个后端服务，需要用户提前手动启动好 semantic:8003、agents:8002（MOCK=1）、engine:8001。"
