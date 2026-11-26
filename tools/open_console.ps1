# XT-HUB 一键打开控制台
# 读 robot-ip.txt → 检查车是否在线 → 打开浏览器

$ErrorActionPreference = 'SilentlyContinue'
$here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ipFile = Join-Path $here 'robot-ip.txt'

Write-Host ''
if (-not (Test-Path $ipFile)) {
    Write-Host '[x] 还没有记录车的地址，请先双击「找车.bat」' -ForegroundColor Yellow
    Read-Host '按回车退出'
    exit 1
}

$ip = (Get-Content $ipFile -Raw).Trim()
if (-not $ip) {
    Write-Host '[x] robot-ip.txt 是空的，请先「找车」' -ForegroundColor Yellow
    Read-Host '按回车退出'
    exit 1
}

Write-Host ('正在检查 http://{0}:8000 ...' -f $ip)
$state = $null
try {
    $r = Invoke-WebRequest -Uri ("http://{0}:8000/healthz" -f $ip) -TimeoutSec 5 -UseBasicParsing
    $state = $r.Content.Trim()
} catch { }

if ($state -like 'ok*') {
    Write-Host ('[ok] 车在线：{0}' -f $state) -ForegroundColor Green
    Start-Process ("http://{0}:8000" -f $ip)
    Write-Host '已用默认浏览器打开。账号找管理员要（zwh 是管理员）。'
} else {
    Write-Host ('[x] 连不上 {0}，车可能没开机或不在同一个网络' -f $ip) -ForegroundColor Red
    $ans = Read-Host '要重新找车吗？(Y/n)'
    if ($ans -ne 'n' -and $ans -ne 'N') {
        & (Join-Path $here 'find_robot.ps1')
    } else {
        Read-Host '按回车退出'
    }
}
