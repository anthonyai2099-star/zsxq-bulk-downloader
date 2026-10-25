# tools-zsxq-pdf-downloader

把 [zsxq-pdf-downloader 技能](https://github.com/silentdog918/zsxq-pdf-downloader-skill) 改造成本机可直接运行的版本：用 Playwright 驱动本机浏览器，登录一次知识星球后，按群组 + 日期范围批量下载帖子里的 PDF 附件。

原技能依赖 Claude in Chrome 扩展提供的 `tabs_context_mcp` / `javascript_tool` / `find` 等 MCP 工具，本机没有这些工具，因此这里只保留它的**流程知识**（见 [docs/original-skill.md](docs/original-skill.md)），执行层换成本地浏览器自动化。

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

三步走：**登录一次 → 试跑确认识别 → 正式下载**。

```powershell
# 1. 登录（弹出浏览器，手动扫码，回车退出；登录态写入 .browser-profile）
.\.venv\Scripts\python.exe src\zsxq_dl.py login

# 2. 试跑：只识别不下载，确认群组、日期、PDF 都被认出来了
.\.venv\Scripts\python.exe src\zsxq_dl.py download --group "探索者01" --days 3 --dry-run

# 3. 正式下载
.\.venv\Scripts\python.exe src\zsxq_dl.py download --group "探索者01" --days 7 --out "$HOME\Downloads\zsxq"
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--group` / `--group-url` | 群组名模糊匹配，或直接贴群组页面链接（更稳） |
| `--days N` | 只处理最近 N 天（默认 7） |
| `--since YYYY-MM-DD` | 指定起始日期，优先于 `--days` |
| `--out DIR` | 下载目录，默认 `~/Downloads/zsxq` |
| `--max-scrolls N` | 最多滚多少屏（默认 60） |
| `--limit N` | 本次最多下几个，调试用 |
| `--dry-run` | 只列出识别结果，不点击 |
| `--force` | 同名文件已存在也重新下 |

## 识别不准怎么办

页面改版会导致「PDF 卡片」或「下载文件」按钮定位失败。先导出真实结构：

```powershell
.\.venv\Scripts\python.exe src\zsxq_dl.py probe
# 浏览器里手动进入群组、滚到有 PDF 的位置，回到终端按 Enter
# 产出 probe/page.html、probe/probe.json、probe/screen.png
```

然后把 `probe.json` 里的 `pdf_candidates` 与 `page.html` 拿出来，调整 `src/zsxq_dl.py` 顶部的两个 JS 片段（`TAG_PDFS_JS` 决定什么算 PDF 附件，`MODAL_TEXT_RE` 决定下载按钮文案）。

## 已知限制

- **内容保护**：群主开启「仅 App 可下载」时，网页端没有下载按钮，脚本会识别并跳过，不尝试绕过。
- **日期只按页面上的日期标签估算**：用于决定何时停止滚动，不是精确过滤；`--dry-run` 输出的日期范围可用于核对。
- **需人工登录**：不处理账号密码，登录必须在浏览器里手动完成。
- **下载入口依赖 DOM**：知识星球改版后需要按上面的 probe 流程校准一次。
- 同名文件默认跳过，不会产生 `(1)(2)` 垃圾文件。

## 部署 / 发布

本机工具，不发布。拷贝整个目录（不含 `.venv`、`.browser-profile`、`probe`、`downloads`）即可在另一台机器复现。

## 进度（2026-10-26 暂停）

已完成：

- 原技能已安装到 `C:\Users\anthony\.claude\skills\zsxq-pdf-downloader\`（DSH 从该目录加载技能，新会话生效）
- 本机版脚本、README、离线自检 fixture 已就绪

未完成（下次接着做）：

1. `.venv` 里装 Playwright —— 卡在下载 38.8 MB wheel（清华镜像无进展），可换源重试：
   `.venv\Scripts\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple/ playwright`
2. 跑离线自检：`.venv\Scripts\python.exe tests\smoke.py`（不需要知识星球账号）
3. 真实环境校准：`login` 登录 → `probe` 导出页面结构 → 按需修 `TAG_PDFS_JS` / `MODAL_TEXT_RE`
4. 用 `--dry-run` 验证群组与日期识别，再正式批量下载

已知风险：下载按钮文案与 PDF 卡片结构未在真实页面验证过，首次必须走 `probe`。
