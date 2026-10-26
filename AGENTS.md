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

- `.browser-profile/` 存登录态，**不进 git**；`probe/`、`.tmp/`、下载产物同样忽略。
- 页面结构变化时先跑 `probe` 导出 HTML/JSON，再改 `src/zsxq_dl.py` 顶部的 `FILE_SELECTOR` / `DOWNLOAD_SELECTOR`。
- 切群组必须按 group_id 导航 URL，点侧栏群组名不会刷新信息流。
- 不要改走 `api.zsxq.com`：官方明确拦截非官方工具（code 1059）。
- 内容保护（仅 App 可下载）只识别、不绕过。

## 部署 / 发布

仅本机使用，不发布。
