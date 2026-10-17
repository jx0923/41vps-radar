"""从论坛 favicon 生成站点所需的各种尺寸图标。

输入是论坛现有的 64x64 PNG（LS 品牌图标）。
输出：
  favicon.ico          多尺寸 ICO（16/32/48），浏览器标签页用
  icon-192.png         Android / PWA
  icon-512.png         PWA / 高分辨率
  apple-touch-icon.png iOS 主屏（180x180，需不透明背景）

注意：源图只有 64x64，放大到 512 会有插值模糊，但 favicon 实际
只用 16-32px，视觉上没问题；512 版本仅为兼容部分浏览器/PWA 规范。
"""
import os
import sys

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "ls_favicon.png")
OUT = sys.argv[2] if len(sys.argv) > 2 else "site"

os.makedirs(OUT, exist_ok=True)

im = Image.open(SRC).convert("RGBA")
print("  源图: %s  %s" % (SRC, im.size))

# ---- favicon.ico（多尺寸，浏览器会挑最合适的）----
ico_path = os.path.join(OUT, "favicon.ico")
im.save(ico_path, format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)])
print("  favicon.ico        %d 字节" % os.path.getsize(ico_path))

# ---- PNG 图标 ----
for size, name in ((192, "icon-192.png"), (512, "icon-512.png")):
    p = os.path.join(OUT, name)
    im.resize((size, size), Image.LANCZOS).save(p, format="PNG",
                                                optimize=True)
    print("  %-18s %d 字节" % (name, os.path.getsize(p)))

# ---- apple-touch-icon：iOS 会自己加圆角，且不支持透明 ----
# 用图标自身的背景色填充，避免透明区域变黑。
bg = im.getpixel((im.width // 2, 4))          # 取顶部中间的背景色
canvas = Image.new("RGB", (180, 180), bg[:3])
icon = im.resize((180, 180), Image.LANCZOS)
canvas.paste(icon, (0, 0), icon)
at = os.path.join(OUT, "apple-touch-icon.png")
canvas.save(at, format="PNG", optimize=True)
print("  apple-touch-icon   %d 字节（背景色 %s）"
      % (os.path.getsize(at), bg[:3]))
