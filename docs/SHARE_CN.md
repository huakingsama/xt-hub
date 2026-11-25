# 让别人也能用：三条路，从简单到彻底

先分清两件事，很多人卡在这里：

| | 谁能连 | 需要什么 | 适合 |
|---|---|---|---|
| **同局域网** | 同一 WiFi / 同一交换机下的人 | 一个 IP 地址 | 实验室、教室、公司内网 —— **今天就能用** |
| **跨网络** | 任何地方的人 | 一台有公网 IP 的服务器，或内网穿透 | 远程演示、异地协作 |
| **没硬件** | 只想看界面的人 | 一个 zip / exe | 汇报、评审、培训 |

---

## 一、同局域网（零配置，5 分钟）

### 1. 在"有机器人的那台电脑"上启动

```bash
python hub_server.py --port 8000
# 或者双击  启动.bat
```

启动时会直接把地址打出来：

```
XT-HUB on http://0.0.0.0:8000  (dry-run=False demo=False)

  本机打开 : http://127.0.0.1:8000
  局域网给 : http://192.168.110.199:8000
  别人连不上时检查：同 WiFi？Windows 防火墙放行 8000 端口？
```

**把「局域网给」那一行发给别人**，他们在浏览器打开就能登录。

### 2. 放行防火墙（只做一次）

Windows 第一次运行会弹"是否允许"，点允许即可。
要是当时点了取消，双击仓库里的 **`开放防火墙-8000.bat`**（会自动请求管理员权限）。

Linux：

```bash
sudo ufw allow 8000/tcp
```

### 3. 给别人开账号

**用 admin 登录 → 顶栏「管理」→ `/admin` 页面**：

- 填用户名 + 密码 + 选角色 → **添加/重置**
- 角色只有三种：

| 角色 | 能做什么 |
|---|---|
| `viewer` | 只能看：地图、融合图、相机、状态灯 |
| `operator` | 能看 + **接管控制权**后开车、启停传感器栈、采集三维 |
| `admin` | operator + 管理用户、强制释放控制权、看审计日志 |

不想一个个手点，也可以直接写文件（不用启动服务）：

```bash
python set_users.py            # 按脚本里的 TEAM 表批量写/重置
python set_users.py --list     # 看现有账号
python set_users.py --keep-admin   # 保留出厂 admin
```

密码只存 pbkdf2-sha256（120000 轮 + 每人独立 salt），`config.json` 里没有明文，也不进 git。

> 同一时刻只有 **1 个 operator** 能发指令（90 秒租约 + 30 秒心跳），其他人照样能看画面。
> 人走了没退出？租约 90 秒后自动过期；急的话 admin 点「强制释放」。

### 4. 手机能不能看

能。手机连同一个 WiFi，浏览器输 `http://<那个IP>:8000` 就行。
画面是 MJPEG，一路 15fps 约 30KB/s，十个人同时看也不会把机器人拖垮
（服务端是 `ThreadingHTTPServer`，`request_queue_size=64`，实测 6 个客户端拿到的完全是同一帧）。

---

## 二、跨网络（别人不在同一个 WiFi）

前提说清楚：**机器人/PC 通常没有公网 IP**，所以必须借一个中转。

### 方案 A：内网穿透 `cloudflared`（最省事，不用服务器、不用改路由器）

```bash
# 1. 装（Windows）
winget install --id Cloudflare.cloudflared

# 2. 起一条临时隧道（把本机 8000 暴露成一个 https 域名）
cloudflared tunnel --url http://127.0.0.1:8000
```

它会打印一个 `https://xxxx-xxxx.trycloudflare.com` 的地址，**把这个发给别人**。
不用注册、不用备案，关掉窗口就失效。缺点：地址每次重启都变，速度一般。

要固定地址就得注册 Cloudflare 账号 + 自己的域名，`cloudflared tunnel create` 建命名隧道。

### 方案 B：自己的服务器 + `frp`（稳定，我们有 `slam-178` 可用）

服务器（`192.168.129.178`，SSH 8000 端口，用户 `zwh`）当 `frps`：

```bash
# 服务器上
wget https://github.com/fatedier/frp/releases/download/v0.61.0/frp_0.61.0_linux_amd64.tar.gz
tar xf frp_*.tar.gz && cd frp_*_linux_amd64
./frps -c frps.toml        # frps.toml: bindPort = 7000
```

机器人/PC 当 `frpc`：

```toml
# frpc.toml
serverAddr = "192.168.129.178"
serverPort = 7000
[[proxies]]
name = "xthub"
type = "tcp"
localIP = "127.0.0.1"
localPort = 8000
remotePort = 8000
```

```bash
./frpc -c frpc.toml
```

别人访问 `http://192.168.129.178:8000`。

> ⚠️ 那台服务器**磁盘已经 100%（剩 6.5G）**，装 frp 前先清空间；
> 它**自身出不了网**，但作 `frps` 只需要别人能连进来，能连就行。

### 方案 C：`Tailscale`（组虚拟局域网，最安全）

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

装完每台机器（你的、同事的、机器人的）都有一个 `100.x.x.x` 地址，互相像在同一局域网。
适合"固定几个人长期用"，不用暴露到公网。缺点：每个使用者都得装客户端。

### 安全底线（无论哪条路）

1. **别用默认密码**。`--init-admin 新密码` 或登录后改。
2. 公网暴露时，**至少再加一层**：Cloudflare Access / frp 的 `httpBasicAuth` / Nginx Basic Auth。
3. `audit.jsonl` 记着谁在什么时候动了什么，出问题先看它。

---

## 三、别人没有机器人

### 演示包（双击即用，不装 Python）

把 `xthub-portable.zip` 发给对方，解压后：

- `启动-演示.bat` → `http://127.0.0.1:8000`（`admin / admin123`）
- 里面是合成的地图/融合/相机三路画面 + 可点的传感器栈、建图模式、采集三维

适合：汇报、评审、给领导看效果、给新同事练手。

### 单文件（有 Python 就行）

```bash
python xthub.pyz --demo --port 8000
```

或者 `pip install xt-hub` 之后直接 `xthub --demo`（要发布到 PyPI）。

---

## 四、把功能搬到车上（部署到真机）

前提：车能 SSH（`xtrobot@<IP>`，出厂密码 `1234`）。

```bash
# PC 上，双击
push-update.bat 192.168.110.44
```

它做三件事：
1. `scp` 上传 `hub_server.py` / `robot_stack.py` / `teleop_bridge.py` / `make3d_html.py`
2. 重启 `xt-hub`（有 systemd 用 systemctl，没有就 nohup 兜底）并确保 `xt-stack` 在跑
3. `curl /healthz` 和 `/status` 自检

装成开机自启（一次性）：

```bash
scp install.sh xtrobot@<IP>:~/
ssh xtrobot@<IP> 'bash ~/install.sh'     # 建 xt-hub.service / xt-stack.service
```

之后别人只要 `http://<车IP>:8000`。

---

## 五、常见问题

**别人打不开，本机能开？**
1. 是不是同一个 WiFi/网段（`192.168.110.x` 对 `10.35.186.x` 是不通的）
2. 防火墙没放行（双击 `开放防火墙-8000.bat`）
3. 车里/PC 上有多个网卡时，监听地址是 `0.0.0.0` 才对（默认就是）

**画面卡、延迟大？**
MJPEG 是逐帧传的，跨公网会慢。三条路：降分辨率、把 `cam_server.py` 的 fps 调到 5、或者只让 1-2 个人看视频、其他人看地图。

**多人同时操作会不会打架？**
不会。写操作要持有租约 token，第二个人的按钮会提示"没有控制权，请先接管"。
接管是抢占式的——新人一接管，旧人的下一次指令就会被拒绝并提示已被接管。

**怎么知道谁在动？**
`/admin` 底部是审计日志（最近 80 条），完整记录在 `audit.jsonl`。
