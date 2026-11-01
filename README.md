# tools-zsxq-pdf-downloader

把 [zsxq-pdf-downloader 技能](https://github.com/silentdog918/zsxq-pdf-downloader-skill) 改造成本机可直接运行的版本：用 Playwright 驱动本机浏览器，登录一次知识星球后，按群组 + 日期范围批量下载帖子里的附件（默认 PDF）。

原技能依赖 Claude in Chrome 扩展提供的 `tabs_context_mcp` / `javascript_tool` / `read_page` 等 MCP 工具，本机没有这些工具，因此这里只保留它的**流程知识**（见 [docs/original-skill.md](docs/original-skill.md)），执行层换成本地浏览器自动化。

## 技术栈

- Python 3.12 + Playwright（同步 API）
- 浏览器：本机 Microsoft Edge（`channel="msedge"`），失败自动回退 Chromium
- 独立浏览器 profile：`.browser-profile/`，登录态本地保存，不进 git

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 使用

**登录一次 → 确认群组 → 试跑 → 正式下载**。

```powershell
# 1. 登录：弹出浏览器，微信扫码；登录态写入 .browser-profile（之后不用再扫）
.\.venv\Scripts\python.exe src\zsxq_dl.py login

# 2. 看自己加入了哪些群组（带 group_id）
.\.venv\Scripts\python.exe src\zsxq_dl.py groups

# 3. 试跑：只列出识别到的附件，不下载
.\.venv\Scripts\python.exe src\zsxq_dl.py dry-run --group "系统技术" --days 7

# 4. 正式下载
.\.venv\Scripts\python.exe src\zsxq_dl.py download --group "系统技术" --days 7 --out "$HOME\Downloads\zsxq"
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--group` | 群组名模糊匹配，自动解析成 id 后跳转 |
| `--group-id` | 群组 id（`groups` 命令能看到），最稳 |
| `--group-url` | 群组完整链接 |
| `--days N` | 只处理最近 N 天（默认 7） |
| `--since YYYY-MM-DD` | 指定起始日期，优先于 `--days` |
| `--ext pdf` | 附件类型，逗号分隔，如 `pdf,docx` |
| `--out DIR` | 下载目录，默认 `downloads/`（见下方说明） |
| `--limit N` | 本次最多成功下载几个，调试用 |
| `--force` | 同名文件已存在也重新下 |
| `--headless` | 无头模式（看不到浏览器窗口） |

## 按帖子导出（一篇一个文件夹）

`export` 子命令会按帖子建文件夹，把该帖所有附件放进去，不写正文：

```powershell
.\.venv\Scripts\python.exe src\zsxq_dl.py export --group "系统技术" --days 30 --folder-name "系统技术"
```

产出结构：

```
downloads/系统技术/
├── 2026-10-26_美日“利剑27”联合实兵演习…/
│   ├── 美日利剑27演习…仿真技术报告.docx
│   └── …（该帖全部附件）
├── 2026-10-25_俄罗斯“菲林”喷气推进巡航导弹…/
└── _manifest.json          # 每个附件的状态：downloaded / skipped / failed
```

导出专用参数：

| 参数 | 说明 |
| --- | --- |
| `--folder-name` | 群组子目录名，默认用 `--group` 的值 |
| `--ext *` | 附件类型过滤，默认全部 |
| `--batch N` | 每尝试 N 个文件重启一次浏览器会话（默认 3） |
| `--retries N` | 单个文件最多重试次数（默认 2） |
| `--delay` | 每个文件之间的间隔秒数 |
| `--out DIR` | 根目录，默认 `downloads/` |
| `--existing DIR` | 已下载目录，命中同名文件就跳过（可重复，增量补跑用） |
| `--match k1,k2` | 只下载标题/正文命中关键字的帖子（逗号分隔，默认任一命中） |
| `--match-all` | 要求全部关键字命中 |
| `--title-only` | 只匹配标题，避免正文随口提一句也被算进来 |
| `--skip k1,k2` | 标题含这些词的帖子跳过 |

## 按兴趣筛选下载

内容太多时先搜后下，`search` 只扫描不下载：

```powershell
# 90 天里标题含「无人机 / 防空 / 航母」的帖子，只列清单
.\.venv\Scripts\python.exe src\zsxq_dl.py search --group "系统技术" --days 90 `
  --match "无人机,防空,航母" --title-only --out search.json

# 确认后只下这些主题
.\.venv\Scripts\python.exe src\zsxq_dl.py export --group "系统技术" --days 90 `
  --match "无人机,防空,航母" --title-only `
  --out "D:\CLAUDE-CODE\Text\_exports\zsxq" --existing "D:\知识星球下载\系统技术"
```

`search` 的输出是 `日期 | 附件数 | 标题`，可以直接挑；要排除某几篇就用 `--skip` 传标题里的特征词。

## 偏好（长期有效）

**先读 [preferences.md](preferences.md)**：宏观战略 / 战法 / 作战概念优先级最高，不能以「偏战略、和装备无关」为由排除；其次是成体系的装备技术。

关键字集合在 [topics.json](topics.json)，分组维护（`macro` 组标了 `priority: high`）。筛帖时直接吃这套配置：

```powershell
# 用默认偏好（宏观 + 反无人机 + 空中 + 海上 + 精确打击）
.\.venv\Scripts\python.exe src\zsxq_dl.py search --group "系统技术" --days 90 --title-only

# 只启用其中几组
.\.venv\Scripts\python.exe src\zsxq_dl.py search --group "系统技术" --days 90 --title-only --only macro,uav
```

`--match` 的临时关键字会和 `--profile` 合并去重，所以「固定偏好 + 临时加词」可以一起用。

## 长期存放与增量下载（重要约定）

**长期库固定在 `D:\知识星球下载\<群组名>\`**，这是唯一需要备份的地方。

Python 子进程被沙箱限制只能写工作区，写 `D:\知识星球下载` 会 `PermissionError`，所以流程是「先落暂存区，再搬过去」：

```powershell
# 1. 导出到工作区暂存区，同时告诉它去哪儿找已下载的文件
.\.venv\Scripts\python.exe src\zsxq_dl.py export `
  --group "系统技术" --days 30 --folder-name "系统技术" `
  --out "D:\CLAUDE-CODE\Text\_exports\zsxq" `
  --existing "D:\知识星球下载\系统技术"

# 2. 搬到 D 盘长期库，并合并清单
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-to-d.ps1
```

> 本机执行策略禁止直接运行 .ps1，必须带 `-ExecutionPolicy Bypass`；`pwsh` 也不在 PATH 里，用 `powershell`。

**增量规则**：任何时候要更大范围（比如这次 30 天、下次 60 天），都只要把 `--days` 改大、`--existing` 指向长期库即可，已经下过的文件按「帖子文件夹 + 文件名」自动跳过，不会重复下载。

> 路径别名：暂存区 `D:\CLAUDE-CODE\Text\_exports\zsxq\<群组>`、长期库 `D:\知识星球下载\<群组>`。别把 C 盘的临时副本当作库，C 盘那份只是给用户看一眼的拷贝。

## 真实页面结构（2026-10 校准）

| 元素 | 选择器 |
| --- | --- |
| 附件卡片 | `div.file-name`（文字即文件名，点击弹出「文件详情」） |
| 下载按钮 | `div.btn.download`（弹窗内，文字「下载文件」） |
| 群组侧栏 | `span.group-name`，外层 `<a href="/group/{id}">` |
| 帖子时间 | `2026-10-26 07:22` |

三个实测坑：

1. **切换群组必须走 URL**。点侧栏群组名只改 SPA 路由，信息流不刷新，附件数会读成 0；必须解析出 group_id 后 `goto` 群组页。
2. **不能走 API**。`api.zsxq.com` 对非官方工具返回 `code 1059`（"不支持非官方工具访问"），只保留浏览器模拟点击这条路。
3. **弹窗不会自己关**。下载完成后「文件详情」弹窗仍在，遮罩会挡住后续点击；Escape 也无效（焦点被下载抢走），必须点遮罩容器关闭。另外同一会话连点三四次后页面会「点不动」，所以按 `--batch` 重启会话，失败项回队列重试。

## 识别不准怎么办

页面改版会导致附件卡片或下载按钮定位失败。先导出真实结构：

```powershell
.\.venv\Scripts\python.exe src\zsxq_dl.py probe --group "系统技术" --scroll 3
# 产出 probe/page.html、probe/probe.json、probe/screen.png
```

然后对照 `probe.json`，调整 `src/zsxq_dl.py` 顶部的 `FILE_SELECTOR` / `DOWNLOAD_SELECTOR`。

## 离线自检

不需要登录，用本地 fixture 页面验证「识别 → 点击 → 弹窗 → 下载 → 落盘 → 内容保护」全链路：

```powershell
.\.venv\Scripts\python.exe tests\smoke.py
```

## 已知限制

- **内容保护**：群主开启「仅 App 可下载」时弹窗里没有下载按钮，脚本识别并跳过，不尝试绕过。
- **日期只按页面上的时间标签估算**：用来决定何时停止滚动，不是精确过滤；`dry-run` 会输出页面日期范围供核对。
- **需人工登录**：不处理账号密码，二维码要在浏览器里手动扫；登录态有效期由知识星球决定，过期后重跑 `login` 即可。
- **同名文件默认跳过**，不会产生 `(1)(2)` 垃圾文件；`--force` 可覆盖。
- 下载的是你自己账号有权限的内容，脚本只做批量点击，不绕过任何权限或保护。

## 部署 / 发布

本机工具，不发布。拷贝整个目录（不含 `.venv`、`.browser-profile`、`.tmp`、`probe`）即可在另一台机器复现。

## 状态（2026-11-01）

- 登录态持久化有效，重启浏览器不用重扫
- **长期库：`D:\知识星球下载\系统技术\`，193 篇帖子 / 739 个附件 / 1.24 GB，覆盖 2026-01 ~ 2026-10 全年**
  - 按月：1 月 18 篇、2 月 14 篇、3 月 26 篇、4 月 14 篇、5 月 22 篇、6 月 16 篇、7 月 14 篇、8 月 15 篇、9 月 23 篇、10 月 31 篇
  - 筛选口径：`topics.json` 默认五组（宏观战法、反无人机、空中力量、海上力量、精确打击），只匹配标题
- 全部 739 个附件通过文件头校验，无 0 字节、无损坏、无空目录
- `_manifest.json` 739 条，按实际磁盘内容重建
- 离线自检 3/3 通过

## 批量下载的已知坑（2026-10-30 补）

1. **信息流加载慢**：每批 20 篇要 5–10 秒，等待不足会被误判「没有更多」，导致只加载 20 篇。
2. **一次加载 90 天（120 篇）容易失败**：改成按 `--since/--until` 分两段跑，每段约 40–80 篇。
3. **同一会话连点 3–4 个附件后会「点不动」**：靠 `--batch` 定期重启会话 + 失败回队列重试。
4. **同名帖子**（同一天重发、附件不同）：定位附件必须「日期 + 标题 + 文件名」三者一起匹配。
5. **网络抖动**（DNS 解析失败、Edge 偶发启动失败）：会话启动带 8 次退避重试。
