#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 XT-HUB 图标（雷达扫描 + 小车轮廓），输出多尺寸 .ico"""
import math
import os
from PIL import Image, ImageDraw

S = 512
BG_TOP = (17, 24, 39)      # slate-900
BG_BOT = (8, 12, 20)
ACC1 = (56, 189, 248)      # sky-400
ACC2 = (59, 130, 246)      # blue-500
FG = (226, 232, 240)


def rounded_mask(size, r):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    return m


def base():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # 竖向渐变底
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        c = tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3))
        gd.line([(0, y), (S, y)], fill=c + (255,))
    img.paste(grad, (0, 0), rounded_mask(S, int(S * 0.22)))
    return img


def radar(img):
    d = ImageDraw.Draw(img, "RGBA")
    cx = cy = S / 2
    R = S * 0.36

    # 外圈 + 两道内圈
    for k, w in ((1.00, 8), (0.66, 6), (0.33, 5)):
        r = R * k
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ACC2 + (110,), width=w)

    # 十字准线
    d.line([cx - R, cy, cx + R, cy], fill=ACC2 + (70,), width=4)
    d.line([cx, cy - R, cx, cy + R], fill=ACC2 + (70,), width=4)

    # 扫描扇形（从 -50° 到 0°，带羽化）
    for i in range(46):
        a = math.radians(-52 + i)
        alpha = int(18 + 130 * (i / 45.0))
        r = R * 0.995
        d.pieslice([cx - r, cy - r, cx + r, cy + r], math.degrees(a) - 1.2,
                   math.degrees(a) + 0.4, fill=ACC1 + (alpha,))

    # 扫描前沿（亮线）
    a = math.radians(0)
    d.line([cx, cy, cx + R * math.cos(a), cy - R * math.sin(a)],
           fill=ACC1 + (255,), width=9)

    # 目标点
    for (ang, dist, rr) in ((0.62, 0.58, 13), (2.5, 0.42, 10), (4.1, 0.72, 8)):
        px = cx + R * dist * math.cos(ang)
        py = cy - R * dist * math.sin(ang)
        d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=(255, 255, 255, 235))

    # 中心点
    d.ellipse([cx - 16, cy - 16, cx + 16, cy + 16], fill=(255, 255, 255, 255))
    return img


def chassis(img):
    """底部一个小车轮廓，暗示这是机器人"""
    d = ImageDraw.Draw(img, "RGBA")
    y = int(S * 0.845)
    w, h = int(S * 0.34), int(S * 0.075)
    x0 = (S - w) // 2
    d.rounded_rectangle([x0, y, x0 + w, y + h], radius=h // 2,
                        fill=FG + (240,))
    # 轮子
    for wx in (x0 + int(w * 0.18), x0 + int(w * 0.82)):
        r = int(h * 0.55)
        d.ellipse([wx - r, y + h - r // 2, wx + r, y + h + r + r // 2],
                  fill=ACC2 + (255,))
    # 顶部雷达头
    r2 = int(S * 0.045)
    d.ellipse([S // 2 - r2, y - r2 * 2, S // 2 + r2, y - 1], fill=ACC1 + (255,))
    return img


def main():
    img = base()
    img = chassis(img)     # 先画车（在下层）
    img = radar(img)
    # 稍微把雷达上移，给车留空间
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xthub.ico")
    png = out.replace(".ico", ".png")
    img.save(png)
    img.save(out, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("wrote", out, os.path.getsize(out), "bytes")
    print("wrote", png)


if __name__ == "__main__":
    main()
