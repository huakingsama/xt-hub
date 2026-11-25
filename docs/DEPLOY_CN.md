# 部署手册（机器人端）

## 0. 前置检查

```bash
ssh <user>@<robot-ip>                       # 能登录
python3 -c "import sys;print(sys.version)"  # 3.7+ 即可
pgrep -f rosmaster                          # 建图栈是否已在跑（可选）
```

## 1. 上传文件

```bash
scp hub_server.py install.sh teleop_bridge.py <user>@<robot-ip>:~/
```

## 2. 装成开机自启

```bash
ssh <user>@<robot-ip> "bash ~/install.sh"
```

`install.sh` 做四件事：

1. 写 `~/.config/systemd/user/xt-hub.service`（或 `/etc/systemd/system/`，按权限自动选）
2. `systemctl enable --now xt-hub`
3. 打印访问地址与首次密码
4. 失败时降级为 `nohup` 后台运行，不阻塞部署

## 3. 首次登录

浏览器打开 `http://<robot-ip>:8000`，账号 `admin` / `admin123`。

**第一件事是改密码**：

```bash
ssh <user>@<robot-ip> "cd ~ && python3 hub_server.py --user admin 你的新密码 admin"
```

## 4. 加人

```bash
python3 hub_server.py --user zhangsan 密码 operator
python3 hub_server.py --user guest 密码 viewer
```

也可以在网页 `/admin` 页面里增删（需要 admin 角色）。

## 5. 遥操作桥（可选）

键盘遥控需要机器人上跑一个 python2 的桥：

```bash
cd ~ && nohup python teleop_bridge.py >/dev/null 2>&1 &
curl -s http://127.0.0.1:8099/health
```

返回里 `cmd_subs` 就是 `/cmd_vel` 的订阅者数量：

- `cmd_subs: 0` → 底盘驱动没起，遥控不会有效果（页面会提示，但不要以为是网页 bug）
- `cmd_subs: 1+` → 正常

开机自启可加到 `~/.bashrc` 或建一个 systemd 单元（参考 `install.sh` 的写法）。

## 6. 端口一览

| 端口 | 服务 | 谁在听 |
|---|---|---|
| 8000 | XT-HUB 控制台 | hub_server.py |
| 8090 | 相机 MJPEG | cam_server.py |
| 8091 | 地图 PNG | mapview.py |
| 8093 | 雷达+深度融合 | fuse_view.py |
| 8099 | 遥操作桥 | teleop_bridge.py |

只需对外开放 **8000**，其余可以只绑 `127.0.0.1`。

## 7. 排障

| 现象 | 检查 | 处理 |
|---|---|---|
| 登录后白屏 | `netstat -ano \| findstr :8000` | 有多个 PID → 旧实例，`taskkill /F` 后重启 |
| 页面打开但地图黑 | `curl :8000/api/status` | `hector:false` → 建图没起 |
| 遥控无反应 | `curl :8099/health` | `cmd_subs:0` → 底盘驱动 |
| 点目标点报错 | 同上 | `move_base` 未部署，属预期 |
| 别人连不上 | 防火墙 | `ufw allow 8000` 或 Windows 防火墙放行 |

## 8. 卸载

```bash
systemctl --user disable --now xt-hub      # 或 sudo systemctl ...
rm -f ~/.config/systemd/user/xt-hub.service ~/hub_server.py ~/config.json ~/audit.jsonl
```
