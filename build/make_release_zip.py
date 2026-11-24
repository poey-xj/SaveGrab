"""
把构建产物打成规范的 zip（正斜杠路径 + UTF-8 文件名）。

PowerShell 的 Compress-Archive 在 PS 5.1 里会把路径写成反斜杠，
7-Zip / WinRAR 等工具解压会报错，所以统一用这个脚本打包。

用法：
    python build/make_release_zip.py <源目录> <输出.zip> [额外文件...]
"""
from __future__ import annotations

import os
import sys
import zipfile

# 不打包进去的垃圾文件
SKIP_NAMES = {"preview.png", "error.log", "cli.log"}
SKIP_DIRS = {"__pycache__"}

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_EXTRAS = [
    "README.md",
    "PUBLISH.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "启动.bat",
    "preview.png",
    "preview-login.png",
    os.path.join("docs", "视频脚本.md"),
    os.path.join("docs", "GITHUB文案.md"),
    os.path.join("docs", "FAQ.md"),
]


def add_tree(zf: zipfile.ZipFile, root: str, prefix: str = "") -> int:
    count = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(files):
            if name in SKIP_NAMES:
                continue
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            arcname = f"{prefix}{rel}" if prefix else rel
            zf.write(full, arcname, zipfile.ZIP_DEFLATED, compresslevel=6)
            count += 1
    return count


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src, out = sys.argv[1], sys.argv[2]
    extras = sys.argv[3:] or [os.path.join(PROJECT, rel) for rel in DEFAULT_EXTRAS]
    if os.path.exists(out):
        os.remove(out)
    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        total += add_tree(zf, src)
        for extra in extras:
            if not os.path.exists(extra):
                print("  skip missing:", extra)
                continue
            arcname = os.path.basename(extra)
            zf.write(extra, arcname, zipfile.ZIP_DEFLATED, compresslevel=6)
            total += 1
    size = os.path.getsize(out)
    print(f"packed {total} files -> {out} ({size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
