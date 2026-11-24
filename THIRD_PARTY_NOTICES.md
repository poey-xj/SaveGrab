# 第三方组件声明

本项目的运行依赖以下开源组件，发布时请一并保留本文件。

## 核心

| 组件 | 版本 | 许可证 | 项目地址 |
|---|---|---|---|
| Legendary (`legendary-gl`) | 0.21.1 | GPL-3.0-or-later | https://github.com/legendary-gl/legendary |
| requests | 2.34.2 | Apache-2.0 | https://github.com/psf/requests |
| urllib3 | 2.8.0 | MIT | https://github.com/urllib3/urllib3 |
| certifi | 2026.11.20 | MPL-2.0 | https://github.com/certifi/python-certifi |
| charset-normalizer | 3.5.3 | MIT | https://github.com/jawah/charset_normalizer |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |
| pycryptodomex | 3.24.2 | BSD-2-Clause / Public Domain | https://github.com/Legrandin/pycryptodome |
| filelock | 4.3.1 | Unlicense | https://github.com/tox-dev/filelock |

## 说明

- Legendary 以 GPL-3.0-or-later 发布。本项目内置其源码（`vendor/legendary`）并通过其 API 工作，
  因此**整体按 GPL-3.0-or-later 分发**，必须附带完整源码。
- `vendor/` 中的纯 Python 依赖均为宽松许可证，可随包分发；`Cryptodome`（pycryptodomex）
  含一个编译好的 `.pyd`，来自官方 wheel。
- 本项目未修改 Legendary 的代码，只是调用它的接口。

## 商标

Epic Games、Epic Games Store、Death Stranding 等名称与商标归各自权利人所有。
本项目与 Epic Games 无关联，也未获得其背书。
