# 贡献与维护笔记

## 技术栈

- Python 3.10+ / Playwright（sync API）
- 浏览器：本机 Microsoft Edge（`channel="msedge"`），失败回退 Chromium

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tests\smoke.py      # 离线自检，不需要账号
```

## 约定

- `.browser-profile/` 存登录态，**绝不提交**；`probe/`、`downloads/`、`.tmp/` 同样忽略
- 页面改版时先跑 `probe` 导出 HTML/JSON，再改 `src/zsxq_dl.py` 顶部的 `FILE_SELECTOR` / `DOWNLOAD_SELECTOR`
- 切群组必须按 `group_id` 导航 URL，点侧栏群组名不会刷新信息流
- 不要改走 `api.zsxq.com`：官方明确拦截非官方工具（code 1059）
- 内容保护（仅 App 可下载）只识别、不绕过

## 提交前

```powershell
.\.venv\Scripts\python.exe -m py_compile src\zsxq_dl.py
.\.venv\Scripts\python.exe tests\smoke.py
git status --short   # 确认没有 .browser-profile / downloads 被带上
```
