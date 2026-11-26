# XT-HUB 客户端（桌面软件）

给**使用者**用的 Windows 桌面程序。双击打开 → 自动在局域网找车 → 点「进入控制台」→ 独立窗口（无地址栏）登录使用。

![client](screenshots/client.png)

## 它解决什么问题

浏览器方案要求使用者自己记住 `http://<车 IP>:8000`，车换了 IP 就得重新问人。
客户端把这件事做掉了：启动就扫一遍局域网，列出所有在跑的 XT-HUB，并标注哪个是"本机自己"（没有真实画面）。

## 打包

```bat
build-client.bat
```

产物：`release\client_build\XTHUBClient\`（onedir，含 `_internal`），再打成
`release\XT-HUB-Client-v1.0.zip`（约 12 MB，982 个文件）。

用 PyInstaller 的 `--onedir` 而不是 `--onefile`：单文件版启动时要把自己解压到 `%TEMP%`，
在受限环境（无写权限、TEMP 被策略管）会直接报
`[PYI-xxxxx:ERROR] Could not create temporary directory!`，改用目录版 + 短路径更稳。

## 分发给队友

把 `XT-HUB-Client-v1.0.zip` 发过去，让他们：

1. 解压到任意位置
2. 双击「安装到桌面.bat」（会复制到 `%LOCALAPPDATA%\XTHUBClient` 并建桌面快捷方式）
3. 双击桌面图标 → 选车 → 登录

不需要安装 Python，不需要管理员权限。

## 技术要点

- 扫描：对每个本机网段的 /24 并发探测 8000 端口（分 128 一批，避免线程爆），
  命中后请求 `/healthz` 拿状态
- 打开方式：优先 `msedge.exe --app=<url>` / `chrome.exe --app=<url>`，
  即无地址栏的独立窗口，看起来像原生软件；没有则退回默认浏览器
- 记住上次的 IP（`%APPDATA%\XTHubClient\client.json`），下次启动先试它
- 列表里带 `[本机]` 前缀的是你自己电脑上跑的实例，选中会提示"没有真实画面"

## 界面文字

`客户端窗口` → 找车结果；`控制台窗口` → 由 hub 提供的网页：

![console](screenshots/console.png)
