# XT-HUB 找车工具（兼容 Windows PowerShell 5.1）
# 扫描本机所在网段，找出正在跑 XT-HUB 的机器人，结果写入 robot-ip.txt

$ErrorActionPreference = 'SilentlyContinue'
$here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ipFile = Join-Path $here 'robot-ip.txt'

Write-Host ''
Write-Host '=== 正在找车（扫描局域网） ===' -ForegroundColor Cyan
Write-Host ''

# 1) 本机网段（/24 粒度）
$prefixes = @()
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
    ForEach-Object {
        $o = $_.IPAddress.Split('.')
        $prefixes += ('{0}.{1}.{2}' -f $o[0], $o[1], $o[2])
    }
$prefixes = $prefixes | Select-Object -Unique

if (-not $prefixes) {
    Write-Host '[x] 没有可用网卡，是不是没连 Wi-Fi？' -ForegroundColor Red
    exit 1
}
Write-Host ('本机网段: ' + ($prefixes -join ', '))
Write-Host '探测 8000 端口（约 2 秒）...'

# 2) 一次性发起异步连接，统一等 1.2 秒后看谁连上了
$probes = New-Object System.Collections.ArrayList
foreach ($p in $prefixes) {
    for ($i = 1; $i -le 254; $i++) {
        $ip = "$p.$i"
        $c  = New-Object System.Net.Sockets.TcpClient
        $null = $c.BeginConnect($ip, 8000, $null, $null)
        [void]$probes.Add([pscustomobject]@{ IP = $ip; C = $c })
    }
}
Start-Sleep -Milliseconds 1200

$hits = @()
foreach ($pr in $probes) {
    if ($pr.C.Connected) { $hits += $pr.IP }
    $pr.C.Close()
}

if (-not $hits) {
    Write-Host ''
    Write-Host '[x] 没找到车。请检查：' -ForegroundColor Yellow
    Write-Host '    1) 车通电了吗（屏幕亮、右上角 Wi-Fi 已连上）'
    Write-Host '    2) 电脑和车连的是同一个路由吗'
    Write-Host '    3) 车上的服务：ssh 到车执行 systemctl status xt-hub'
    Write-Host ''
    Read-Host '按回车退出'
    exit 2
}

Write-Host ''
Write-Host '找到以下 XT-HUB：' -ForegroundColor Green
$self = (Get-NetIPAddress -AddressFamily IPv4).IPAddress
foreach ($h in $hits) {
    $state = '(无响应)'
    try {
        $r = Invoke-WebRequest -Uri ("http://{0}:8000/healthz" -f $h) -TimeoutSec 4 -UseBasicParsing
        $state = $r.Content.Trim()
    } catch { }
    $tag = ''
    if ($self -contains $h) { $tag = '  <- 这台电脑自己' }
    Write-Host ('    http://{0}:8000    {1}{2}' -f $h, $state, $tag)
}

# 3) 优先选"不是本机"的那个；只找到本机就明确提示
$target = $hits[0]
$others = @($hits | Where-Object { $self -notcontains $_ })
if ($others.Count -gt 0) {
    $target = $others[0]
} else {
    Write-Host ''
    Write-Host '[!] 只找到这台电脑自己跑的 XT-HUB，没找到车。' -ForegroundColor Yellow
    Write-Host '    如果只是想在本机看界面，可以继续；要看车的真实画面，请让车上电并连同一个 Wi-Fi。'
    $go = Read-Host '继续用本机这个吗？(y/N)'
    if ($go -ne 'y' -and $go -ne 'Y') {
        Write-Host '已取消。'
        Read-Host '按回车退出'
        exit 3
    }
}

Set-Content -Path $ipFile -Value $target -Encoding ASCII -NoNewline
Write-Host ''
Write-Host ('[ok] 选定: http://{0}:8000' -f $target) -ForegroundColor Green
Write-Host ('     已写入 {0}' -f $ipFile)

$ans = Read-Host '现在打开控制台？(Y/n)'
if ($ans -ne 'n' -and $ans -ne 'N') { Start-Process ("http://{0}:8000" -f $target) }
