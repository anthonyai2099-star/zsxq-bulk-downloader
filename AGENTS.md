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
.venv\Scripts\python.exe src\zsxq_dl.py download --group "群组名" --days 7 --dry-run
```

## 关键约定

- `.browser-profile/` 存登录态，**不进 git**；`probe/`、下载产物同样忽略。
- 页面结构变化时先跑 `probe` 导出 HTML/JSON，再改 `src/zsxq_dl.py` 顶部的选择器常量。
- 内容保护（仅 App 可下载）只识别、不绕过。

## 部署 / 发布

仅本机使用，不发布。
