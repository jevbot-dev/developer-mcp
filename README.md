# Developer MCP

[Developer](https://apps.apple.com/app/apple-developer/id640199958) 的 MCP 桥接包，给 Jevbot 等 agent 用：可以搜索 WWDC 讲座（2014–2026，包括 Tech Talks 和 Meet with Apple）的字幕，再在 Developer 里打开到某一秒。

Developer.app 没有 App Intents，也没有脚本接口。所以这个包从外面替它对 agent 说话，按 [桥接服务约定](https://github.com/jevbot-dev/jevbot-mac/blob/main/docs/app-bridge-contract.md)：

- 检索直接读字幕数据（通道 `data`）
- 打开走 Developer 的 universal link（通道 `link`）

## 工具

| 工具 | 做什么 | 通道 |
|---|---|---|
| `search` | 按相关度排出 session，多个词都要出现；不带关键词时列出过滤条件下的全部 session | `data` |
| `grep` | 字幕里说到某句话的位置，带开始秒数 | `data` |
| `transcript` | 读一段时间范围内的字幕 | `data` |
| `show` | 单个 session 的元数据和相关资源 | `data` |
| `open_at` | 在 Developer 里打开某个 session，定位到某一秒，不自动播放 | `link`，开环 |
| `status` | 数据状态、Developer 是否已安装、最近一次发出的打开请求 | `data` |

- 全部只读。
- 每个工具的 `_meta["dev.jevbot/bridge"]` 写明它走的通道，以及结果能不能确认。
- `open_at` 发出链接后读不到反馈，所以返回 `"verified": false`。

## 运行

- 通过 stdio 运行，由宿主拉起，需要 Node 24 或更新的版本。
- 只调用系统自带的程序：`/usr/bin/open`、`tar`、`sips`、`defaults`。
- `open_at` 用 `open -b developer.apple.wwdc-Release <url>?time=N`。直接 `open` 网址会被默认浏览器接走。

## 数据

包里只有代码。字幕来自 [guitaripod/wwdc-sessions](https://github.com/guitaripod/wwdc-sessions)，内容版权归 Apple：

- 第一次使用时下载这个仓库的归档（约 27 MB），只保留 catalog、metadata 和 transcript，放在 `~/Library/Application Support/developer-mcp/wwdc-sessions`。
- 每 7 天检查一次上游有没有更新，有更新就在后台整体替换。
- 设置环境变量 `WWDC_REPO` 时，直接使用那份本地 clone，不下载。

## 开发与发布

```sh
npm install
npm start            # 从源码以 stdio 运行
npm run build        # dist/developer-mcp/server.mjs：单文件，依赖已打进去
npm run package      # 再生成 release/developer-mcp-<版本>.zip 和 .sha256
```

**发布**：
1. 改 `package.json` 的版本号，提交。
2. 推送标签 `v<版本>`。GitHub Actions（`.github/workflows/release.yml`）会从这个标签构建、生成构建证明，并发布 Release。Release 里带有 zip、`.sha256`，以及写好校验值的商店条目片段 `.catalog.json`。

**核对一个发布包**：

```sh
gh attestation verify developer-mcp-<版本>.zip -R jevbot-dev/developer-mcp   # 确认是哪个提交、由哪个流程构建的
git checkout v<版本> && npm ci && npm run package                          # 自己重新构建，sha256 应该一致
```

zip 是可复现的：条目不压缩，时间戳和权限固定。所以同一份源码和 lockfile，在任何机器上构建出来的字节都相同。
