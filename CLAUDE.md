# tools-zsxq-pdf-downloader

知识星球（wx.zsxq.com）PDF 批量下载工具，给自己用：登录一次后按群组 + 日期范围把帖子里的 PDF 附件批量下载到本地。

## 技术栈

- 语言 / 框架：Python 3.12 + Playwright（sync API）
- 关键依赖：playwright；浏览器用本机 Edge（channel=msedge），回退 Chromium

## 启动

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe src\zsxq_dl.py login
.venv\Scripts\python.exe src\zsxq_dl.py groups
.venv\Scripts\python.exe src\zsxq_dl.py dry-run --group "群组名" --days 7
```

## 关键约定

- **先读 [preferences.md](preferences.md)**：用户偏好宏观战略 / 战法 / 作战概念 > 装备技术细节，禁止以「偏战略、与装备无关」为由筛掉；关键字配置在 [topics.json](topics.json)。
- **长期库固定在 `D:\知识星球下载\<群组>\`**；导出先落工作区暂存区
  `D:\CLAUDE-CODE\Text\_exports\zsxq\<群组>\`，跑完用 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-to-d.ps1` 搬过去并合并清单。
- **增量下载**：扩大时间范围时（30 天→60 天）只改 `--days`，并加
  `--existing "D:\知识星球下载\<群组>"`，已下载文件按「帖子文件夹 + 文件名」自动跳过，不许重复下载。
- Python 子进程只能写工作区，直接写 `D:\知识星球下载` 会 `PermissionError`，不要试图绕过（junction 也会被拦）。
- `.browser-profile/` 存登录态，**不进 git**；`probe/`、`.tmp/`、`.venv/`、`downloads/` 同样忽略。
- 页面结构变化时先跑 `probe` 导出 HTML/JSON，再改 `src/zsxq_dl.py` 顶部的 `FILE_SELECTOR` / `DOWNLOAD_SELECTOR`。
- 切群组必须按 group_id 导航 URL，点侧栏群组名不会刷新信息流。
- 不要改走 `api.zsxq.com`：官方明确拦截非官方工具（code 1059）。
- 内容保护（仅 App 可下载）只识别、不绕过。

## 部署 / 发布

仅本机使用，不发布。
