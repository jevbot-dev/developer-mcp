# developer-mcp

Developer.app 的桥接包（`src/`，Node），给 Jevbot 等 agent 用：搜索 WWDC 讲座和字幕，在 Developer 里打开到某一秒。
另有一个给人用的命令行工具 `wwdc.py`（检索、截帧、剪片段）。

| 位置 | 放什么 |
|---|---|
| `~/ghq/github.com/guitaripod/wwdc-sessions` | 数据（上游仓库，只读；`./wwdc.py update` 拉取） |
| 本仓库 | 代码 |
| `~/Library/Application Support/developer-mcp/` | 桥接包自己下载的数据 |
| `~/media/reference/wwdc/` | 素材输出：`frames/`、`clips/` |

## 命令行检索（`wwdc.py`）

数据源：[guitaripod/wwdc-sessions](https://github.com/guitaripod/wwdc-sessions)，本地在
`~/ghq/github.com/guitaripod/wwdc-sessions`（可用 `$WWDC_REPO` 覆盖）。只用 transcript，视频在 Developer app 里看。

```sh
./wwdc.py search "app intents" --year 2024-2026        # 按相关度排序 session（多个词为 AND）
./wwdc.py search --event wwdc2026 --topic design         # 不带关键词：列出过滤条件下的全部 session
./wwdc.py grep "Liquid Glass" --event wwdc2025 -C 1     # 逐句命中 + 时间戳 + ?time= 跳转链接
./wwdc.py show wwdc2025-219                             # 单个 session 元数据与文件路径
./wwdc.py frames wwdc2026-250 2:00-2:03 5:10.5          # 截指定时间段的每一帧（默认 4K jpg）
./wwdc.py topics --year 2026                            # 主题分布
./wwdc.py update                                        # git pull 更新数据
```

通用过滤：`--year 2025|2023-2026`、`--event`、`--topic`（子串匹配，如 `swiftui`）、`--platform`、`--json`。
匹配选项：`-e` 正则、`-s` 区分大小写、`-n` 条数上限。`search --no-transcript` 只查元数据。

注意：2014–2018 覆盖稀疏；transcript 仅英文；`grep` 按单个字幕片段匹配，跨片段的短语可能漏掉，可改用 `search` 或多个词。

## 桥接包（`developer-mcp`）

按 [桥接服务约定](https://github.com/jevbot-dev/jevbot-mac/blob/main/docs/app-bridge-contract.md) 写。Developer.app 没有 Intent，也没有脚本接口：检索直接读字幕（通道 `data`），打开走 universal link（通道 `link`）。

```sh
npm install
npm run build        # dist/developer-mcp/server.mjs：单文件，依赖已打进去
npm run package      # 再生成 release/developer-mcp-<版本>.zip，并打印 sha256，给 catalog.json 用
npm start            # 直接从源码以 stdio 运行
```

- 运行环境：Jevbot 自带的 Node（v24），通过 stdio 启动。只调用系统自带的程序：`/usr/bin/open`、`tar`、`sips`、`defaults`。
- 数据：第一次使用时，从 GitHub 下载 guitaripod/wwdc-sessions 的归档（约 27 MB），只保留 catalog、metadata 和 transcript，放在 `~/Library/Application Support/developer-mcp/wwdc-sessions`。每 7 天检查一次上游有没有更新，有更新就在后台替换。设置 `WWDC_REPO` 时直接用那份本地 clone，不下载。
- 工具：`search` / `grep` / `show` / `transcript`（读某段时间的字幕）/ `open_at`（在 Developer 里打开到某一秒，不自动播放）/ `status`。全部只读。
  - 每个工具的 `_meta["dev.jevbot/bridge"]` 写明它走的通道，以及结果能不能确认。
  - `open_at` 是开环的，返回 `"verified": false`。
  - `open_at` 用 `open -b developer.apple.wwdc-Release <url>?time=N`：直接 `open` 网址会被默认浏览器接走。
- 本机开发用的 Jevbot 配置：`~/Library/Application Support/Jevbot/mcp-apps/developer.apple.wwdc-Release.json`，`stdio` 指向 Jevbot 自带的 Node 和本仓库 `dist/developer-mcp/server.mjs`。从商店安装时用的是 `catalog.json` 里的配置（`${node}`、`${bundle}`）。
