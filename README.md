# 知识星球批量下载工作

> `zsxq-bulk-downloader` —— 把一个知识星球（zsxq.com）里的附件，按「一篇帖子一个文件夹」批量归档到本地。

知识星球网页端没有批量导出功能，App 里也只能一条条点。这个项目用 Playwright 驱动本机浏览器、模拟真人操作，把一个星球的历史附件按帖子整理成本地资料库，适合做个人知识库归档。

## 特性

- **一篇帖子一个文件夹**：文件夹名 `日期_标题`，该帖所有附件落在里面，另附 `_manifest.json` 清单
- **按时间范围筛选**：`--days` / `--since` / `--until`，可按月切片跑
- **按主题筛选**：关键字只匹配标题，避免正文随口提一句就被算进来
- **增量补漏**：已下载的文件按「文件夹 + 文件名」自动跳过，扩大范围不会重复下载
- **断点续跑**：失败项回到队列重试；页面「点不动」时自动重启浏览器会话
- **内容保护识别**：群主开启「仅 App 可下载」时弹窗里没有下载按钮，脚本识别并跳过，不绕过

## 和其他方案的区别

- **不走 API**：zsxq 官方对非官方工具直接返回 `code 1059`（"不支持非官方工具访问"），所以只保留浏览器点击这一条路。
- **不依赖 Claude in Chrome**：原始思路来自 [zsxq-pdf-downloader-skill](https://github.com/silentdog918/zsxq-pdf-downloader-skill)，那套依赖 MCP 工具；这里用 Playwright 落到本机，不需要任何扩展。

## 环境要求

- Windows 10/11
- Python 3.10+
- Microsoft Edge（系统自带即可，不需要装 Chromium）

## 安装

```powershell
git clone https://github.com/<your-name>/zsxq-bulk-downloader.git
cd zsxq-bulk-downloader
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 快速开始

```powershell
# 1. 登录：弹出浏览器，微信扫码；登录态存到 .browser-profile，之后不用再扫
.\.venv\Scripts\python.exe src\zsxq_dl.py login

# 2. 看自己加入了哪些星球（带 group_id）
.\.venv\Scripts\python.exe src\zsxq_dl.py groups

# 3. 先搜：只列清单，不下载
.\.venv\Scripts\python.exe src\zsxq_dl.py search --group "系统技术" --days 90 --title-only

# 4. 导出：一篇帖子一个文件夹
.\.venv\Scripts\python.exe src\zsxq_dl.py export --group "系统技术" --days 30 --out .\downloads
```

## 输出结构

```
downloads/系统技术/
├── 2026-10-26_美日利剑27联合实兵演习作战体系与战术演进解析/
│   ├── 美日利剑27演习MATLAB仿真技术报告.docx
│   ├── 利剑27演习MATLAB仿真源码.zip
│   └── ...            # 该帖全部附件
├── 2026-10-25_俄罗斯菲林喷气推进巡航导弹技术特征解析/
└── _manifest.json     # 每个附件的记录：所属文件夹、文件名、大小
```

## 命令一览

| 命令 | 作用 |
| --- | --- |
| `login` | 打开浏览器扫码登录，登录态持久化 |
| `groups` | 列出已加入的星球名和 `group_id` |
| `search` | 按时间/关键词搜帖子，只输出清单 |
| `dry-run` | 列出识别到的附件，不点击 |
| `export` | 按帖子导出附件（主命令） |
| `download` | 不分文件夹，平铺下载匹配的附件 |

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--group` / `--group-id` / `--group-url` | 目标星球，`group-id` 最稳 |
| `--days N` / `--since` / `--until` | 时间范围，`--since/--until` 优先 |
| `--title-only` | 只匹配标题（推荐） |
| `--match k1,k2` | 临时关键词，和 `--profile` 合并 |
| `--profile topics.json` | 偏好关键字文件（默认读取项目内 topics.json） |
| `--only macro,uav` | 只启用偏好文件里的某几组 |
| `--skip k1,k2` | 标题含这些词的帖子跳过 |
| `--existing DIR` | 已下载目录，命中同名文件就跳过（可重复） |
| `--out DIR` | 输出根目录 |
| `--batch N` | 每尝试 N 个文件重启一次浏览器会话（默认 3） |
| `--retries N` | 单个文件最多重试次数 |
| `--delay` | 每个文件之间的间隔秒数 |
| `--headless` | 无头模式，不弹窗口 |

## 偏好配置

`topics.json` 里按主题分组维护关键词，`macro` 组标了 `priority: high`：

```json
{
  "default": ["macro", "uav", "air", "sea", "precision"],
  "groups": {
    "macro": { "label": "宏观战略 / 战法", "priority": "high", "keywords": ["演习", "战争", "战略", "杀伤链"] },
    "uav":   { "label": "反无人机", "keywords": ["无人机", "反无人", "蜂群"] }
  }
}
```

`search` 和 `export` 默认就吃这套配置，也可以 `--only macro,air` 临时收窄。`preferences.md` 写了这套配置背后的取舍逻辑。

## 增量补漏

隔一段时间想补新的，把范围开到上次之前，已下载的会自动跳过：

```powershell
.\.venv\Scripts\python.exe src\zsxq_dl.py export `
  --group-id 12345678901234 `
  --since 2026-09-01 `
  --title-only `
  --existing "D:\zsxq-library\系统技术"
```

## 实现要点（踩过的坑）

1. **信息流加载慢**：每批 20 篇要 5–10 秒，等待不足会被误判「没有更多」，只能加载到 20 篇。现在用真实滚轮事件 + 4 秒等待 + 停滞 5 批才停。
2. **一次加载太多会失败**：90 天 ≈ 120 篇尚可，再往前（300+ 篇）会加载不全。按 `--since/--until` 分月切片最稳。
3. **同一会话连点 3–4 个附件后会「点不动」**：弹窗遮罩残留导致，`--batch` 定期重启会话 + 失败回队列。
4. **下载后弹窗不会自己关**：Escape 也失效（焦点被下载抢走），必须点遮罩容器关闭。
5. **同名帖子**：同一天可能重发同名帖（附件不同），定位附件必须「日期 + 标题 + 文件名」三者一起匹配。
6. **切群组必须走 URL**：点侧栏群组名只改 SPA 路由，信息流不刷新，附件数会读成 0。
7. **网络抖动**：DNS 失败、Edge 偶发启动失败都会中断整批，会话启动带 10 次退避重试 + profile 锁清理。

## 目录结构

```
src/zsxq_dl.py          主程序（CLI + Playwright 流程）
scripts/sync-to-d.ps1   把暂存区文件搬到长期库并合并清单（可选）
tests/fixture.html      模拟知识星球 DOM 的离线页面
tests/smoke.py          离线自检
topics.json             偏好关键词
preferences.md          偏好取舍说明
docs/original-skill.md  原始 skill 存档（流程参考）
```

## 离线自检

不需要账号，用本地 fixture 验证「识别 → 点击 → 弹窗 → 下载 → 落盘 → 内容保护」全链路：

```powershell
.\.venv\Scripts\python.exe tests\smoke.py
```

## 已知限制

- 仅在 Windows + Edge 上验证，其他平台需要改浏览器 channel 和 `.ps1` 脚本
- 登录必须人工扫码，脚本不处理账号密码
- 知识星球页面改版后需要跑 `probe` 重新校准选择器
- 大范围回溯很慢：300 篇的加载深度下，单次会话光滚动就要 5–10 分钟

## 免责声明

本项目仅用于批量下载**你自己有权访问**的内容，方便个人离线归档。请遵守知识星球的用户协议与内容保护设置，不要把下载到的付费内容二次传播。使用本工具产生的一切后果由使用者自行承担。

## License

[MIT](LICENSE)
