# XT-HUB · 机器人多人协作控制台

> 一台 ROS 小车（XT-R1 / 树莓派 / 工控机都行），一个网页，多人同时看、一个人开。

XT-HUB 是一个**单文件、零依赖**的机器人远程协作控制台。它跑在机器人本机上，把
「实时地图 / 雷达+深度融合 / 相机画面 / 键盘遥控 / 导航目标点 / 轨迹录制回放」装进
一个网页，用一套**共享-抢占**规则解决"多人抢一台车"的问题。

```
        ┌──────────┐   HTTP   ┌───────────────────────────┐
        │ 浏览器 A │ ───────► │                           │
        ├──────────┤          │   XT-HUB  (跑在机器人上)   │
        │ 浏览器 B │ ───────► │   :8000                   │  ┌──────────┐
        ├──────────┤          │   · 会话 / 租约 / 审计     │─►│  /scan   │
        │ 浏览器 C │ ───────► │   · 画面代理 · 指令下发    │  │  /map    │
        └──────────┘          └───────────────────────────┘  │ /cmd_vel │
                                                              └──────────┘
```

## 为什么把 hub 放在机器人上

| 方案 | 视频路径 | 指令路径 | 别人电脑关机 | 结论 |
|---|---|---|---|---|
| hub 在 PC | PC 上行 → 再转发给其他人 | PC → 机器人 | **全员断线** | 不行 |
| **hub 在机器人** | 机器人直出，多客户端并发 | 本机 subprocess | 无影响 | **采用** |

## 核心规则：读是广播，写是抢占

- **看**（地图/相机/融合）：不限人数，人人可看。
- **开**（遥控/建图/存图/急停）：同一时刻只有一个人有权限，靠 **90 秒租约 + 30 秒心跳** 管理，超时自动释放 —— 不会出现"人走了车还锁着"。
- 所有写操作落 `audit.jsonl`，页面右侧实时显示"谁在什么时候干了什么"。

## 功能

| 模块 | 说明 |
|---|---|
| 实时地图 | 代理 `map_server` 输出的 PNG，1.2s 刷新；叠加机器人位姿与历史轨迹 |
| 融合俯视 | 雷达点 + 深度相机点云俯视投影（橙/蓝双色） |
| 相机 | MJPEG 实时流，掉线自动重连 |
| 键盘遥控 | `W/S/A/D` 10Hz 下发 `/cmd_vel`，松手即停，限速可调，**0.6s 看门狗**兜底 |
| 导航目标 | 点地图任意位置 → 发 `/move_base_simple/goal` |
| 录制回放 | 0.5s 采样位姿存 JSON，前端插值重放，用于演示与复盘 |
| 演示模式 | `--demo` 无需机器人，合成三路画面，用来讲方案 / 做 UI 联调 |
| 活动审计 | 登录、接管、指令、失败原因全记录 |

## 快速开始

### 方式一：不接机器人，先看界面（演示模式）

```bash
python hub_server.py --demo --dry-run --port 18300
# 打开 http://127.0.0.1:18300 ，账号 admin / admin123
```

Windows 用户也可以直接双击 `run-demo.bat`。

### 方式二：部署到机器人

```bash
# 1. 拷到机器人
scp hub_server.py install.sh teleop_bridge.py <user>@<robot-ip>:~/

# 2. 装成开机自启服务（端口 8000）
ssh <user>@<robot-ip> "bash ~/install.sh"

# 3. 浏览器打开
http://<robot-ip>:8000
```

Windows 下也可以双击 `deploy.bat`，它会自动找 `robot-ip.txt`、上传、装服务、自检。

### 方式三：打成单文件程序

**A. `.pyz`（无需联网、不需要 pip，任何 python3 都能跑）**

```bash
bash build-pyz.sh          # Linux / macOS
build-pyz.bat              # Windows
python3 xthub.pyz --demo --dry-run --port 18300
```

**B. `.exe`（连 Python 都不需要）**

- 本地：`build-exe.bat`（需要 `pip install pyinstaller`）
- 云端：推一个 `v*` tag，GitHub Actions 自动构建并把 `xthub.exe` 挂到 Release

```bash
git tag v1.0.0 && git push origin v1.0.0
```

产物在 Actions 的 Artifacts，打 tag 时同时挂 Release。双击 `xthub.exe --demo` 即可跑。

## 命令行参数

| 参数 | 说明 |
|---|---|
| `--port 8000` | 监听端口 |
| `--demo` | 演示模式：合成地图/融合/相机三路画面，不连机器人 |
| `--dry-run` | 演练模式：指令只回显不执行，适合培训和评审 |
| `--user <name> <pw> [role]` | 新增/重置用户（role: admin / operator / viewer） |

首次运行会自动生成 `config.json` 并创建 `admin / admin123`，**请立刻改密码**。

## HTTP 接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/live` | 登录 | 控制台页面 |
| GET | `/admin` | admin | 用户管理、审计查询 |
| GET | `/healthz` | 公开 | 存活探针，返回 `ok HH:MM:SS demo=...` |
| GET | `/api/lease` | 登录 | 当前持有者、剩余秒数 |
| POST | `/api/lease/claim` | 登录 | 接管（返回 token） |
| POST | `/api/lease/release` | 登录 | 释放 |
| POST | `/api/lease/heartbeat` | 持 token | 续约 |
| GET | `/api/status` | 登录 | 雷达 Hz、建图进程是否在跑 |
| GET | `/api/state` | 登录 | 位姿、轨迹、地图元数据 |
| POST | `/api/teleop` | 持 token | `{lin,ang}` 速度指令 |
| POST | `/api/goal` | 持 token | `{x,y,th}` 导航目标 |
| POST | `/api/cmd?action=` | 持 token | `start / stop / save / status` |
| GET/POST | `/api/rec/*` | 登录/持 token | 轨迹录制与回放 |

## 截图

| 实时地图 + 位姿 | 雷达+深度融合 |
|---|---|
| ![map](screenshots/sample_map.png) | ![fuse](screenshots/sample_fuse.png) |

## 常见问题

**Q: 登录后白屏？**
多半是**旧实例还占着端口**。`HTTPServer` 带 `SO_REUSEADDR`，同端口能起多个进程，
请求会被轮询到旧代码。先 `netstat -ano | findstr :8000` 找到 PID，`taskkill /PID <pid> /F`，再重启。

**Q: 页面能开但地图是黑的？**
`/api/status` 的 `hector` 为 false，说明建图进程没起。地图是"算出来的"，不是"传过来的"。

**Q: 遥控没反应？**
`teleop_bridge.py` 的 `/health` 会返回 `/cmd_vel` 订阅者数量，为 0 说明底盘驱动没起（通常是没有里程计节点）。

## 技术约束

- 纯标准库，Python 3.7+，**不需要 pip install**。
- 单文件部署，配置热加载，日志按 JSONL 追加。
- 只在局域网使用：默认密码公开，务必改掉；不要直接暴露到公网，如需外网请套 Nginx + HTTPS + 强密码。

## License

MIT
