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

**为什么默认不直接写 `~/Downloads`**：本机沙箱下 Python 子进程只能写工作区，写 `C:\Users\...\Downloads` 会 `PermissionError`。先落到项目 `downloads/`，再用 PowerShell 搬走即可（我这边就是这么做的）。

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

## 状态（2026-10-27）

已跑通真实环境：

- 登录态验证通过（`.browser-profile` 持久化，重启浏览器仍有效）
- 群组解析：3 个群组 id 全部正确
- `download`：近 3 天 PDF 全部落盘，重复文件自动跳过
- `export`：`系统技术` 近 3 天 **3 篇帖子 / 18 个附件 / 24.8 MB**，全部下载成功，0 失败；docx/pptx/zip 完整性校验通过
- 离线自检 3/3 通过
