"""Download PyInstaller and friends into build_tools/ (no pip needed)."""
import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile

WD = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.normpath(os.path.join(WD, "..", "build_tools"))
os.makedirs(DEST, exist_ok=True)

PACKAGES = [
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "altgraph",
    "pefile",
    "pywin32-ctypes",
    "packaging",
    "setuptools",
]

PY = f"cp{sys.version_info.major}{sys.version_info.minor}"


def compatible(name: str) -> bool:
    if not name.endswith(".whl"):
        return False
    if name.endswith("-py3-none-any.whl") or name.endswith("-py2.py3-none-any.whl"):
        return True
    if f"-{PY}-{PY}-win_amd64.whl" in name:
        return True
    if re.search(r"-cp3\d+-abi3-win_amd64\.whl$", name):
        return True
    if re.search(r"-py3-none-win_amd64\.whl$", name):
        return True
    return False


def simple_index(pkg: str) -> list[str]:
    url = f"https://pypi.org/simple/{pkg}/"
    req = urllib.request.Request(url, headers={"User-Agent": "build-script"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        html = resp.read().decode("utf-8", "replace")
    links = re.findall(r'href="([^"]+)"', html)
    out = []
    for link in links:
        clean = link.split("#")[0]
        fname = clean.rsplit("/", 1)[-1]
        if compatible(fname):
            out.append((fname, clean))
    return out


def fetch(url: str, tries: int = 5, timeout: int = 180) -> bytes:
    last = None
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "build-script"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"    retry {attempt}: {exc!r}", flush=True)
            time.sleep(2 * attempt)
    raise RuntimeError(f"download failed: {last}")


def main() -> int:
    for pkg in PACKAGES:
        try:
            candidates = simple_index(pkg)
        except Exception as exc:  # noqa: BLE001
            print(f"!! {pkg}: index failed {exc!r}", flush=True)
            continue
        if not candidates:
            print(f"!! {pkg}: no compatible wheel", flush=True)
            continue
        fname, rel = candidates[-1]
        url = "https://pypi.org/" + rel[3:] if rel.startswith("../") else rel
        print(f"[{pkg}] {fname}", flush=True)
        blob = fetch(url)
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                zf.extractall(DEST)
        except zipfile.BadZipFile:
            print(f"    not a zip, skip ({len(blob)} bytes)", flush=True)
            continue
        print(f"    ok {len(blob)} bytes", flush=True)
    print("done ->", DEST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
