# -*- coding: utf-8 -*-
"""set_users.py —— 一次性把团队账号写进 config.json（不需要服务在跑）

用法：
    python set_users.py                 # 用下面的 TEAM 默认表
    python set_users.py --list          # 只看现在有哪些人
    python set_users.py --file 配置路径  # 指定 config.json

设计说明：
  * 密码只存 pbkdf2-sha256（120000 轮）+ 每用户独立 salt，落地文件里没有明文
  * 重复执行是"重置密码"，不会重复加人
  * 默认会删掉出厂账号 admin（避免弱口令留在生产里），--keep-admin 可保留
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hub_server as H  # noqa: E402  （只借用它的 add_user / 配置结构）

TEAM = [
    # (用户名, 密码, 角色)
    ("zwh", "Zwh14514@", "admin"),
    ("zbw", "1234", "operator"),
    ("lyh", "1234", "operator"),
    ("tjc", "1234", "operator"),
    ("sjrx", "1234", "operator"),
]


def main():
    args = sys.argv[1:]
    conf = H.CONF
    for i, a in enumerate(args):
        if a == "--file" and i + 1 < len(args):
            conf = os.path.abspath(args[i + 1])
    if conf != H.CONF:
        H.CONF = conf
    H.CFG = H.load_conf()

    if "--list" in args:
        print("配置文件：%s" % H.CONF)
        for u in H.CFG["users"]:
            print("  %-8s %s" % (u["u"], u["role"]))
        return 0

    print("配置文件：%s" % H.CONF)
    for name, pw, role in TEAM:
        H.add_user(name, pw, role)
        print("  [x] %-6s %-9s 密码 %s" % (name, role, "*" * len(pw)))

    if "--keep-admin" not in args:
        before = len(H.CFG["users"])
        H.CFG["users"] = [x for x in H.CFG["users"] if x["u"] != "admin"]
        if len(H.CFG["users"]) != before:
            H.save_conf(H.CFG)
            print("  [-] 已删除出厂账号 admin")

    print("\n现在总共 %d 个账号：" % len(H.CFG["users"]))
    for u in H.CFG["users"]:
        print("  %-8s %s" % (u["u"], u["role"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
