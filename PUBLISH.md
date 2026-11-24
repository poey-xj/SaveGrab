# 发布到 GitHub 的步骤（照着做就行）

## 0. 上传什么、不上传什么

**要传（源码，约 30 个文件）：**

```
main.py
epic_core.py
README.md
LICENSE
THIRD_PARTY_NOTICES.md
requirements.txt
requirements-dev.txt
.gitignore
启动.bat
assets/            (图标)
build/             (打包脚本：build_exe.bat / fetch_vendor.py / fetch_build_tools.py / make_icon.py)
docs/              (视频脚本)
preview.png
preview-login.png
```

**不要传：**

| 路径 | 原因 |
|---|---|
| `vendor/` | 767 个文件、9.4 MB，含编译好的 `.pyd`；用 `python build/fetch_vendor.py` 一键重建 |
| `dist/` | 编译产物，改用 Release 上传 zip |
| `build_tools/` | 打包工具，10 MB |
| `build/SaveGrab*/` | PyInstaller 中间产物 |
| `*.spec`、`__pycache__/` | 自动生成 |
| `SaveGrab_v0.3.0_win64.zip` | 放 Release，不要进 git（否则仓库暴涨） |

>  `.gitignore` 已经把这些都排除了，正常 `git add .` 不会把它们带进去。

## 1. 注册账号

1. 打开 https://github.com/signup
2. 用户名建议用英文小写 + 连字符，比如 `yourname` / `savesaver`
3. 邮箱要能收验证码，注册完先去邮箱点验证链接
4. **开启两步验证**：Settings → Password and authentication → Enable 2FA
   （GitHub 现在对写代码的账号强制 2FA，早点开省事，用手机 TOTP App 即可）

## 2. 建仓库

1. 右上角 `+` → New repository
2. 填写：
   - Repository name: `savegrab`
   - Description: `不用下载游戏，直接导出 Epic 云存档（支持一键还原）`
   - Public ✅
   - **不要**勾 "Add a README"（我们本地已经有了）
   - License: 选 `GNU General Public License v3.0`（或先不选，上传后再加）
3. Create repository

## 3. 上传代码（两种方式，选一个）

### 方式 A：装 Git（推荐，以后好更新）

```powershell
winget install --id Git.Git -e --source winget
```

装完**重开一个终端**，然后：

```powershell
cd <你的项目目录>   # 例如 D:\code\savegrab
git init
git add .
git commit -m "SaveGrab v0.3.0"
git branch -M main
git remote add origin https://github.com/<你的用户名>/savegrab.git
git push -u origin main
```

第一次 push 会弹浏览器登录，按提示授权即可。

### 方式 B：网页上传（不装 Git）

GitHub 仓库页 → `Add file` → `Upload files` → 把上面「要传」的文件和文件夹拖进去 →
Commit changes。

注意：网页上传**一次最多 100 个文件**，所以 `vendor/` 千万别拖进去，
其他源码文件数量不多，分两次传也够。

## 4. 发 Release（把 exe 给大家下载）

1. 仓库页右侧 `Releases` → `Create a new release`
2. Tag version: `v0.3.0`（选 `Create new tag on publish`）
3. Title: `v0.3.0 初版`
4. 描述框里写更新内容（可以直接抄 README 的「它能做什么」）
5. 附件拖入 `SaveGrab_v0.3.0_win64.zip`（33 MB，GitHub 支持单文件 2 GB）
6. Publish release

> Release 页会自动提供该 tag 的源码 zip，GPL-3.0 要求的「提供源码」就满足了。
> 再稳妥一点：在 README 顶部加一句「发布版源码见 Releases 的 Source code」。

## 5. 仓库设置（让更多人搜到）

- About 右侧齿轮 → 填 Description，Topics 建议：
  `epic-games` `cloud-save` `save-backup` `death-stranding` `tkinter` `python` `game-save`
- 勾选 Issues（方便收 bug 反馈）

## 6. 上传前最后检查

- [ ] `README.md` 里的截图路径对（`preview.png` 在根目录）
- [ ] `LICENSE` 是 GPL-3.0 全文（已包含）
- [ ] `THIRD_PARTY_NOTICES.md` 里写明了 Legendary 的来源和许可证
- [ ] 仓库里没有你的账号信息：
      `user.json`、`cli.log`、`ecs-home/`、`error.log` 都**不在**项目目录里（已确认）
- [ ] README 或简介里写了「仅用于导出自己账号的存档」

## 7. 以后怎么更新

```powershell
git add .
git commit -m "修了 xxx"
git push
```

发新版本时重复第 4 步，tag 改成 `v0.3.1`，附件换成新 zip。
