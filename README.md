# wwdc-mcp

WWDC session 检索（`wwdc.py`）和给 agent 用的 MCP 服务（`wwdc_mcp.py`）。

| 位置 | 放什么 |
|---|---|
| `~/ghq/github.com/guitaripod/wwdc-sessions` | 数据（上游仓库，只读；`./wwdc.py update` 拉取） |
| 本仓库 | 代码 |
| `~/media/reference/wwdc/` | 素材输出：`frames/`、`clips/` |

## 检索

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

## MCP 服务（给 Jevbot 等 agent 用）

```sh
./wwdc_mcp.py        # http://127.0.0.1:6791/mcp（WWDC_MCP_PORT 可改端口）
```

工具：`search` / `grep` / `show` / `transcript`（读某段时间的字幕）/ `open_at`（在 Developer app 里打开到某一秒，不自动播放）/ `status`。全部只读。
`open_at` 用 `open -a Developer <url>?time=N`：直接 `open` 网址会被默认浏览器接走。
Jevbot 配置：`~/Library/Application Support/Jevbot/mcp-apps/developer.apple.wwdc-Release.json`（挂在 Developer 名下）。
