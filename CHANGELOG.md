# Changelog

本项目从一份 Claude Skill 改造而来，按使用中踩到的坑逐步演进。

## 2026-11-09

- 增量补漏：扫描 2026-09 至今，新增 26 个附件
- 开源整理：补 README / LICENSE / .gitattributes / CHANGELOG

## 2026-11-01

- 补齐 2026 年 1–10 月，累计 197 篇帖子 / 765 个附件 / 1.29 GB
- 修复 Windows 作业被杀后无法续跑的问题（落盘即安全，重跑自动跳过）

## 2026-10-30

- `search` 支持 `--profile` / `--only`，按偏好分组筛选
- 同名帖子定位改为「日期 + 标题 + 文件名」三者匹配
- 空信息流自动重载；Edge 启动失败也纳入退避重试

## 2026-10-28

- 新增偏好体系：`topics.json` 分组关键字 + `preferences.md` 取舍说明
- `export` 新增 `--existing`，实现增量补跑
- 新增 `search` 子命令，只扫描不下载

## 2026-10-27

- 按真实 DOM 重写选择器（`div.file-name` / `div.btn.download`）
- 新增 `export`：一篇帖子一个文件夹
- 切群组改为按 `group_id` 导航（点侧栏不刷新信息流）
- 修复下载后弹窗残留导致后续点击失效

## 2026-10-26

- 首个可用版本：Playwright 驱动本机 Edge，`login` / `probe` / `download`
- 离线 fixture 自检（识别、点击、下载、内容保护）
