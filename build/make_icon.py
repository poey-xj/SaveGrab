"""生成应用图标 assets/app.ico（深色圆角底 + 蓝色云 + 下箭头）。"""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "assets")
os.makedirs(OUT_DIR, exist_ok=True)

SIZE = 1024
BG = (32, 34, 43, 255)       # #20222b
CLOUD = (79, 140, 255, 255)  # #4f8cff
CLOUD_DARK = (58, 111, 216, 255)
ARROW = (232, 234, 242, 255)


def rounded_rect(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def build() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 底
    rounded_rect(d, (0, 0, SIZE, SIZE), int(SIZE * 0.22), BG)

    # 云：三个圆 + 一个圆角矩形
    cy = int(SIZE * 0.44)
    r1 = int(SIZE * 0.135)
    r2 = int(SIZE * 0.175)
    r3 = int(SIZE * 0.125)
    d.ellipse((int(SIZE * 0.20), cy - r1, int(SIZE * 0.20) + 2 * r1, cy + r1), fill=CLOUD)
    d.ellipse((int(SIZE * 0.37), cy - r2, int(SIZE * 0.37) + 2 * r2, cy + r2), fill=CLOUD)
    d.ellipse((int(SIZE * 0.59), cy - r3, int(SIZE * 0.59) + 2 * r3, cy + r3), fill=CLOUD)
    rounded_rect(
        d,
        (int(SIZE * 0.24), cy + int(SIZE * 0.01), int(SIZE * 0.70), cy + int(SIZE * 0.20)),
        int(SIZE * 0.05),
        CLOUD,
    )

    # 下箭头（白色）
    ax = SIZE // 2
    top = int(SIZE * 0.60)
    bot = int(SIZE * 0.78)
    shaft = int(SIZE * 0.035)
    d.rounded_rectangle((ax - shaft, top, ax + shaft, bot - int(SIZE * 0.05)),
                        radius=shaft // 2, fill=ARROW)
    head = int(SIZE * 0.075)
    d.polygon(
        [
            (ax - head, bot - int(SIZE * 0.075)),
            (ax + head, bot - int(SIZE * 0.075)),
            (ax, bot + int(SIZE * 0.035)),
        ],
        fill=ARROW,
    )

    # 底部托盘（暗示"存到本地"）
    d.rounded_rectangle(
        (int(SIZE * 0.24), int(SIZE * 0.86), int(SIZE * 0.76), int(SIZE * 0.885)),
        radius=int(SIZE * 0.012),
        fill=CLOUD_DARK,
    )
    return img


def main():
    img = build()
    ico = os.path.join(OUT_DIR, "app.ico")
    png = os.path.join(OUT_DIR, "app.png")
    img.save(png)
    img.resize((256, 256), Image.LANCZOS).save(
        ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    print("wrote", ico)


if __name__ == "__main__":
    main()
