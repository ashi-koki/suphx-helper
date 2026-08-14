# 小苏菲命令行启动器（suphx_cli.py）

纯标准库、零第三方依赖的命令行工具。复刻「雀魂小苏菲」exe 打开浏览器的方式（使用相同的
`user-data-dir`），实现**登录持久化**：登录一次后，重复调用无需再次登录，登录会话与小苏菲
exe 完全共享。

用它可以把「打开游戏 → 停留 → 关闭」这个过程脚本化，配合任务调度器反复执行。

## 环境要求

- Windows（依赖系统 Chrome、`taskkill`、`PowerShell`）
- Python 3.7+，**无需 `pip install` 任何包**（只用标准库）
- 已安装 Google Chrome（或 Edge；也可在 `settings.json` 的 `custom_browser_path` 里指定）
- 已安装「雀魂小苏菲」，且本脚本放在**小苏菲目录下**（与 exe 同级，即 `_internal` 的上一级）

## 快速开始

1. 把 `suphx_cli.py` 复制到小苏菲目录下。
2. 首次登录：`python suphx_cli.py --login`，在弹出的浏览器里登录一次。
3. 之后即可反复调用，无需再次登录：

```powershell
python suphx_cli.py --open      # 直接进入游戏
python suphx_cli.py             # 默认 = --open --delay 30 -q（打开停留 30 秒后关闭）
```

## 命令一览

| 命令 | 说明 |
|---|---|
| `python suphx_cli.py` | 无参数时默认执行 `--open --delay 30 -q` |
| `--login` | 打开浏览器进登录页并停留（登录后会话自动保存） |
| `--login -q` | 打开浏览器，登录完成后自动退出 |
| `--open` | 直接进入游戏（需已登录过） |
| `--open -q` | 打开游戏，确认已登录后自动退出 |
| `--open --delay 30 -q` | 打开游戏，停留 30 秒后退出（固定时长） |
| `--open -q --timeout 600` | 等待登录最多 600 秒，超时也退出 |
| `--app` | 启动主程序 suphx.exe（其自带 GUI 与 AI 自动打牌） |
| `--proxy` | 浏览器走主程序的 mitm 代理（需 mitm 已在运行） |

常用参数：

- `-q` / `--quiet`：配合 `--login`/`--open`，检测到登录后自动退出。
- `--delay N`：打开后固定停留 N 秒再退出（支持小数，如 `--delay 0.5`）。**不依赖登录判定**，最适合调度器。
- `--timeout N`：`-q` 模式下等待登录的最大秒数（`0` = 一直等，默认）。

退出码：`0` = 已登录 / 正常完成，`1` = 超时未确认登录，`2` = 启动出错（找不到 Chrome 等）。

## 登录判定说明

- 脚本读取 `game.maj-soul.com` 源下的 `localStorage` 中的 `access_token`（雀魂真实登录字段，
  值形如 UUID），非空即视为已登录。
- `--delay N` 是**固定停留**，完全不碰登录判定，最稳定，推荐调度器使用。
- `-q` 不带 `--delay` 时，脚本轮询 Chrome 用户目录下的 `leveldb` 文件判断登录（尽力而为）；
  交互式场景下若判定不准，可在终端按回车手动确认退出。

## 配合 OneDragon ScriptChainer（或其他调度器）

OneDragon 会把 `.py` 内嵌到它自己的 Python 进程里执行，本脚本已为此兼容。配置示例：

```yaml
- display_name: majsoul
  script_type: python
  script_path: C:\...\雀魂小苏菲v2.0.4\suphx_cli.py
  script_process_name: []
  game_process_name: ''
  check_done: ''
  script_arguments: ''            # 留空 = 默认 --open --delay 30 -q
  ...
```

要点：

- `script_arguments` 留空即用默认；也可填 `--open --delay 60 -q` 等自定义停留时长。
- **推荐用 `--delay`**（固定时长），而不是依赖登录判定的 `-q`，因为调度器环境下 stdin 不是终端，
  登录判定只能靠读磁盘文件（尽力而为）。
- 调度器日志里的「5 秒后关闭本窗口」是**调试运行**的正常收尾；正式调度运行不会弹这个，会直接
  继续下一条链，不影响功能。

## 安全提示

- `_internal/data` 是 Chrome 用户目录，里面存着**雀魂登录 token（明文）**；`_internal/settings.json`
  里还有 `online_apikey`。**这些都不要提交到 GitHub 或分享给别人。**
- 分享本工具时，只分享 `suphx_cli.py` 和本 `README.md` 即可。

## 工作原理（简述）

- **打开浏览器**：`subprocess` 调用系统 Chrome，带上 `--user-data-dir=_internal/data`（与小苏菲 exe 相同的用户目录，因此登录共享）。
- **判断登录**：读 `_internal/data/Default/Local Storage/leveldb/` 里的字节，查找 `access_token`。
- **关闭浏览器**：`taskkill` 优雅关闭（发 WM_CLOSE）后，再用 `/F` 强制结束残留（Chrome 主进程会无视 WM_CLOSE，必须 `/F`）。

## 已知限制

- 「自动打 N 局」的 AI 逻辑编译在小苏菲的 `suphx.exe` 内，脚本无法脱离主程序复现；`--app` 仅负责拉起主程序。
- `--login`/`--open` 由本脚本开浏览器，`--app` 由主程序自己开浏览器，两者**不要同时跑**，否则会争抢同一个 Chrome 用户目录导致锁冲突。
