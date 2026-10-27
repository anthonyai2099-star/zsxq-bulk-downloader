#!/usr/bin/env python3
"""知识星球附件批量下载器（Playwright 本地版）。

把 zsxq-pdf-downloader 技能的流程，从「Claude in Chrome 扩展手动点」改成本机脚本：
Playwright 驱动本机 Edge（独立 profile，登录一次长期有效），滚到目标日期范围，
逐个点击附件卡片 -> 「文件详情」弹窗 -> 「下载文件」，抓取浏览器下载并保存。

真实页面结构（2026-10 校准）：
  附件卡片     div.file-name            （文字即文件名，点击弹出文件详情）
  下载按钮     div.btn.download         （弹窗内，文字「下载文件」）
  群组侧栏     span.group-name
  帖子时间     "2026-10-26 07:22"

子命令：
  login    打开浏览器手动登录，保存登录态
  groups   列出已加入的群组名
  probe    导出页面结构，页面改版时用来校准选择器
  download 按群组/日期批量下载附件
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK
    except Exception:  # noqa: BLE001
        pass

from playwright.sync_api import BrowserContext, Error as PWError, Page
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / ".browser-profile"
PROBE_DIR = ROOT / "probe"
TMP_DIR = ROOT / ".tmp"
DEFAULT_OUT = ROOT / "downloads"  # 本机沙箱只允许子进程写工作区，先落这里再搬出去
HOME_URL = "https://wx.zsxq.com/"
GROUP_URL = "https://wx.zsxq.com/group/{gid}"

FILE_SELECTOR = "div.file-name"
DOWNLOAD_SELECTOR = "div.btn.download"
GROUP_NAME_SELECTOR = "span.group-name"
TAG_ATTR = "data-zsxq-file"

INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# 给页面上的附件卡片打标记，返回 {idx, text}
TAG_FILES_JS = r"""
() => {
  const out = [];
  document.querySelectorAll('div.file-name').forEach((el, idx) => {
    const t = (el.textContent || '').trim();
    el.setAttribute('data-zsxq-file', String(idx));
    out.push({idx: idx, text: t});
  });
  return out;
}
"""

# 按帖子聚合：每篇的日期、标题（正文首行）、附件列表（带全局 idx，供点击使用）
POSTS_JS = r"""
() => {
  const dateRe = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:\s+\d{1,2}:\d{2})?$/;
  const cards = [...document.querySelectorAll('app-talk-content')];
  let idx = 0;
  const posts = [];
  for (const card of cards) {
    let box = card;
    let dateEl = null;
    for (let n = 0; n < 6 && box.parentElement; n++) {
      box = box.parentElement;
      dateEl = [...box.querySelectorAll('div,span')].find(e =>
        e.children.length === 0 && dateRe.test((e.textContent || '').trim()));
      if (dateEl) break;
    }
    const files = [...box.querySelectorAll('div.file-name')].map(el => {
      const name = (el.textContent || '').trim();
      el.setAttribute('data-zsxq-file', String(idx));
      return {idx: idx++, name: name};
    });
    const text = (card.innerText || '').trim();
    const title = text.split('\n').map(s => s.trim()).find(Boolean) || '无标题';
    posts.push({
      date: dateEl ? dateEl.textContent.trim() : '',
      title: title,
      text: text,
      text_len: text.length,
      files: files,
    });
  }
  return posts;
}
"""

# 收集页面上的时间标签，用于判断是否滚过目标日期
COLLECT_DATES_JS = r"""
() => {
  const out = [];
  const re = /^(?:(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})|(\d{1,2})[-/.](\d{1,2}))(?:\s+\d{1,2}:\d{2})?$/;
  for (const el of document.querySelectorAll('div,span,time,p,a')) {
    if (el.childElementCount !== 0) continue;
    const t = (el.textContent || '').trim();
    if (!t || t.length > 20) continue;
    if (!re.test(t) && !/^(今天|昨天|前天)$/.test(t)) continue;
    out.push({text: t, y: Math.round(el.getBoundingClientRect().top + window.scrollY)});
  }
  return out;
}
"""

LIST_GROUPS_JS = r"""
() => [...document.querySelectorAll('span.group-name')]
        .map(e => {
          const name = (e.textContent || '').trim();
          const link = e.closest('a');
          const href = link ? (link.getAttribute('href') || '') : '';
          const m = href.match(/group\/(\d+)/);
          return {name: name, group_id: m ? m[1] : ''};
        })
        .filter(g => g.name)
"""


def log(msg: str) -> None:
    print(msg, flush=True)


def sanitize(name: str) -> str:
    name = INVALID_CHARS.sub("_", name).strip().strip(".")
    return name[:150] or "unnamed"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, n = path.stem, path.suffix, 1
    while True:
        candidate = path.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def ensure_temp_dir() -> None:
    """沙箱下系统 TEMP 可能不可写，Playwright 建临时目录会 EPERM，指到项目内。"""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(TMP_DIR)
    os.environ["TMP"] = str(TMP_DIR)


def launch(pw, headless: bool = False) -> tuple[BrowserContext, Page]:
    """启动持久化 profile 的浏览器；优先本机 Edge，失败再退回 Chromium。"""
    ensure_temp_dir()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    common = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        accept_downloads=True,
        viewport={"width": 1440, "height": 960},
        args=["--disable-blink-features=AutomationControlled"],
    )
    errors = []
    for channel in ("msedge", "chrome", None):
        try:
            kwargs = dict(common)
            if channel:
                kwargs["channel"] = channel
            ctx = pw.chromium.launch_persistent_context(**kwargs)
            for old in list(ctx.pages):
                try:
                    old.close()
                except Exception:  # noqa: BLE001
                    pass
            page = ctx.new_page()
            log(f"浏览器已启动（{channel or 'chromium'}），profile: {PROFILE_DIR}")
            return ctx, page
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{channel or 'chromium'}: {exc}")
    raise SystemExit("无法启动浏览器：\n  " + "\n  ".join(errors))


def wait_for_app_ready(page: Page, timeout_s: int = 30) -> None:
    """首页是 SPA，domcontentloaded 后还要等 JS 渲染或跳转 /login。"""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_s * 1_000)
    except PWTimeout:
        pass
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if "/login" in page.url.lower():
            return
        try:
            body = page.inner_text("body", timeout=2_000)
        except PWTimeout:
            body = ""
        if len(body.strip()) > 50:
            return
        page.wait_for_timeout(500)


def on_zsxq(page: Page) -> Page:
    """打开首页；导航偶发 ERR_ABORTED / ERR_TIMED_OUT，退避重试。"""
    last: PWError | None = None
    for attempt in range(3):
        try:
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            wait_for_app_ready(page)
            return page
        except PWError as exc:
            last = exc
            if attempt < 2:
                log(f"打开首页失败（{type(exc).__name__}），{3 * (attempt + 1)}s 后重试……")
                page.wait_for_timeout(3_000 * (attempt + 1))
                try:
                    page = page.context.new_page()
                except PWError:
                    pass
    raise last  # type: ignore[misc]


def looks_logged_out(page: Page) -> bool:
    """拿不到 body（导航中/超时）必须当作未登录，否则会误判成登录成功。"""
    url = page.url.lower()
    if "/login" in url:
        return True
    if "/dweb2" in url or "/group/" in url:
        return False
    try:
        body = page.inner_text("body", timeout=6_000)
    except PWTimeout:
        return True
    body = body.strip()
    if len(body) < 50:
        return True
    return bool(re.search(r"登录知识星球|获取登录二维码|扫码登录", body))


def verify_logged_in(page: Page) -> bool:
    """重新加载首页，确认登录态真的落盘。"""
    try:
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=45_000)
        wait_for_app_ready(page, timeout_s=20)
    except PWError:
        return False
    return not looks_logged_out(page)


def hint_login(page: Page) -> None:
    log("浏览器已停在知识星球登录页，请手动完成：")
    log("  1. 勾选「我已阅读并同意」→ 弹窗点「同意」")
    log("  2. 点「获取登录二维码」，用微信扫码")
    try:
        page.bring_to_front()
    except PWError:
        pass


def wait_until_logged_in(page: Page, timeout_s: int) -> bool:
    """连续两次判定已登录才算数，避开页面跳转瞬间。"""
    deadline = time.time() + timeout_s
    stable = 0
    while time.time() < deadline:
        page.wait_for_timeout(2_000)
        if looks_logged_out(page):
            stable = 0
        else:
            stable += 1
            if stable >= 2:
                return True
    return False


def wait_for_login(page: Page, timeout_s: int = 600) -> None:
    if not looks_logged_out(page):
        return
    log("检测到未登录。")
    hint_login(page)
    log("请用微信扫码登录（二维码在浏览器窗口里），脚本会自动等待……")
    if not wait_until_logged_in(page, timeout_s):
        raise SystemExit("等待登录超时，请先运行 `login`。")
    log("登录成功，继续。")
    page.wait_for_timeout(2_000)


def open_group(
    page: Page,
    group: str | None = None,
    group_id: str | None = None,
    group_url: str | None = None,
) -> None:
    """切换群组。

    实测点击侧栏群组名会触发 SPA 路由但不刷新信息流（附件数为 0），
    所以统一解析出 group_id 后直接导航 URL。
    """
    if group_url:
        page.goto(group_url, wait_until="domcontentloaded", timeout=60_000)
    else:
        if not group_id and group:
            log(f"在左侧列表里查找群组：{group}")
            groups = list_groups(page)
            matched = [g for g in groups if group in g["name"]]
            if not matched:
                available = "、".join(g["name"] for g in groups[:12]) or "（没读到列表）"
                raise SystemExit(
                    f"没找到群组「{group}」。可用的有：{available}\n"
                    f"也可以用 --group-id 直接指定。"
                )
            group_id = matched[0]["group_id"]
            log(f"匹配到：{matched[0]['name']}（{group_id}）")
        if group_id:
            page.goto(GROUP_URL.format(gid=group_id), wait_until="domcontentloaded", timeout=60_000)
        elif "/group/" in page.url:
            log(f"沿用当前已打开的群组：{page.url}")
            return
        else:
            raise SystemExit("需要 --group / --group-id / --group-url 指定群组。")
    wait_for_app_ready(page, timeout_s=30)
    page.wait_for_timeout(2_000)


def list_groups(page: Page) -> list[dict]:
    return page.evaluate(LIST_GROUPS_JS)


def tag_files(page: Page) -> list[dict]:
    return page.evaluate(TAG_FILES_JS)


def collect_dates(page: Page) -> list[dict]:
    return page.evaluate(COLLECT_DATES_JS)


def parse_date_label(text: str, today: date | None = None) -> date | None:
    today = today or date.today()
    text = text.split(" ")[0].strip()
    if text == "今天":
        return today
    if text == "昨天":
        return today - timedelta(days=1)
    if text == "前天":
        return today - timedelta(days=2)
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        for year in (today.year, today.year - 1):
            try:
                candidate = date(year, month, day)
            except ValueError:
                return None
            if candidate <= today:
                return candidate
    return None


def oldest_date_on_page(page: Page) -> date | None:
    dates = [parse_date_label(item["text"]) for item in collect_dates(page)]
    dates = [d for d in dates if d]
    return min(dates) if dates else None


def scroll_until(page: Page, since: date | None, max_scrolls: int, pause: float) -> None:
    """滚到底加载更多。

    实测：进群只加载 20 条帖子，必须滚到页面底部才会按 20 条/批追加；
    「页面高度不变就停」会误判（离底部还远时高度当然不变），所以改为按帖子数增长判断。
    """
    log(f"滚动加载帖子（最多 {max_scrolls} 批，since={since or '不限'}）……")
    count_js = "() => document.querySelectorAll('app-talk-content').length"
    last_count = page.evaluate(count_js)
    stagnant = 0
    for i in range(max_scrolls):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(max(int(pause * 1000), 1_800))
        count = page.evaluate(count_js)
        if since:
            oldest = oldest_date_on_page(page)
            if oldest and oldest < since:
                log(f"已加载到 {oldest}，早于 {since}，停止滚动（共 {count} 篇）。")
                return
        if count > last_count:
            log(f"  第 {i + 1} 批：帖子 {last_count} → {count}")
            last_count, stagnant = count, 0
        else:
            stagnant += 1
            if stagnant >= 3:
                log(f"连续 3 批没有新帖子，停止（共 {count} 篇）。")
                return
    log(f"达到滚动上限，当前 {last_count} 篇。")


def close_modal(page: Page) -> None:
    """关掉「文件详情」弹窗。

    实测：下载完成后弹窗不会自动关，Escape 也无效（焦点可能被下载抢走），
    残留的 .file-preview-container 会挡住后续所有点击。点遮罩容器才能可靠关闭。
    """
    if page.locator(".file-preview-container").count() == 0:
        return
    page.evaluate("() => { const c = document.querySelector('.file-preview-container'); if (c) c.click(); }")
    for _ in range(10):
        if page.locator(".file-preview-container").count() == 0:
            page.wait_for_timeout(300)
            return
        page.wait_for_timeout(200)
    # 兜底：直接摘掉残留节点
    page.evaluate("() => document.querySelectorAll('app-file-preview').forEach(e => e.remove())")
    page.wait_for_timeout(300)


def open_file_card(page: Page, idx: int, name_hint: str) -> bool:
    """点开附件卡片。

    Angular 滚动时会重建节点，自定义的 data 标记会丢，所以标记失效时按文件名精确匹配兜底。
    """
    card = page.locator(f'[{TAG_ATTR}="{idx}"]')
    if card.count() == 0:
        exact = re.compile("^" + re.escape(name_hint.strip()) + "$")
        card = page.locator("div.file-name").filter(has_text=exact).first
        if card.count() == 0:
            log(f"  ! {name_hint}：页面上找不到这个附件，跳过。")
            return False

    try:
        card.scroll_into_view_if_needed(timeout=5_000)
    except PWError:
        pass
    try:
        card.click(timeout=8_000)
        return True
    except PWError:
        pass
    try:
        card.evaluate("el => el.click()")
        return True
    except PWError:
        log(f"  ! {name_hint}：点不开附件，跳过。")
        return False


def download_one(page: Page, idx: int, name_hint: str, out_dir: Path, timeout_s: int) -> Path | None:
    if not open_file_card(page, idx, name_hint):
        return None

    button = page.locator(DOWNLOAD_SELECTOR).first
    try:
        button.wait_for(state="visible", timeout=12_000)
    except PWTimeout:
        # 卡片可能被点击到旧节点，再试一次
        if open_file_card(page, idx, name_hint):
            try:
                button.wait_for(state="visible", timeout=12_000)
            except PWTimeout:
                log(f"  ! {name_hint}：弹窗里没有「下载文件」按钮，可能是内容保护，跳过。")
                close_modal(page)
                return None
        else:
            return None

    try:
        with page.expect_download(timeout=timeout_s * 1000) as info:
            button.click(timeout=10_000)
        download = info.value
    except PWTimeout:
        log(f"  ! {name_hint}：点击后没有触发下载，跳过。")
        close_modal(page)
        return None

    filename = sanitize(download.suggested_filename or name_hint)
    target = unique_path(out_dir / filename)
    download.save_as(str(target))
    close_modal(page)
    return target


def cmd_login(args: argparse.Namespace) -> int:
    with sync_playwright() as pw:
        ctx, page = launch(pw, headless=False)
        page = on_zsxq(page)
        if looks_logged_out(page):
            hint_login(page)
            log(f"脚本会等待 {args.wait}s，期间扫码即可，扫完自动继续……")
            try:
                ok = wait_until_logged_in(page, args.wait)
            except PWError as exc:
                log(f"浏览器窗口已关闭（{str(exc).splitlines()[0]}）。")
                return 1
            if not ok:
                log(f"等了 {args.wait}s 仍未检测到登录，先退出。")
                ctx.close()
                return 1
            if not verify_logged_in(page):
                log("检测到跳转，但重新加载后又回到登录页，登录态没保存成功。")
                ctx.close()
                return 1
            log("登录成功，登录态已验证。")
        else:
            log("当前已是登录状态。")
        ctx.close()
    log(f"登录态已保存在：{PROFILE_DIR}")
    return 0


def cmd_groups(args: argparse.Namespace) -> int:
    with sync_playwright() as pw:
        ctx, page = launch(pw, headless=True)
        page = on_zsxq(page)
        if looks_logged_out(page):
            ctx.close()
            raise SystemExit("未登录，先运行 `login`。")
        page.wait_for_timeout(2_000)
        groups = list_groups(page)
        ctx.close()
    if not groups:
        log("没读到群组列表，页面结构可能变了，跑 `probe` 看看。")
        return 1
    for item in groups:
        log(f"  - {item['name']}  [{item['group_id'] or '未知 id'}]")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx, page = launch(pw, headless=False)
        page = on_zsxq(page)
        if looks_logged_out(page):
            log("未登录，请先在浏览器里登录（自动等待）。")
            hint_login(page)
            if not wait_until_logged_in(page, args.wait):
                ctx.close()
                return 1

        if args.group or args.group_id or args.group_url:
            open_group(page, args.group, args.group_id, args.group_url)

        for _ in range(args.scroll):
            page.evaluate("window.scrollBy(0, 900)")
            page.wait_for_timeout(1_000)
        page.wait_for_timeout(int(args.pause * 1000))

        result = {
            "url": page.url,
            "title": page.title(),
            "groups": list_groups(page),
            "files": tag_files(page),
            "dates": collect_dates(page),
        }
        (PROBE_DIR / "page.html").write_text(page.content(), encoding="utf-8")
        (PROBE_DIR / "probe.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        page.screenshot(path=str(PROBE_DIR / "screen.png"), full_page=False)
        log(f"已导出 {PROBE_DIR}（page.html / probe.json / screen.png）")
        log(f"识别到附件 {len(result['files'])} 个，群组 {len(result['groups'])} 个。")
        ctx.close()
    return 0


def resolve_since(args: argparse.Namespace) -> date | None:
    if getattr(args, "since", None):
        return datetime.strptime(args.since, "%Y-%m-%d").date()
    if getattr(args, "days", None):
        return date.today() - timedelta(days=args.days)
    return None


def match_ext(name: str, exts: list[str]) -> bool:
    lower = name.lower()
    return any(lower.endswith("." + e.lower().lstrip(".")) for e in exts)


def cmd_download(args: argparse.Namespace) -> int:
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    since = resolve_since(args)
    exts = [e.strip() for e in args.ext.split(",") if e.strip()]

    with sync_playwright() as pw:
        ctx, page = launch(pw, headless=args.headless)
        page = on_zsxq(page)
        wait_for_login(page, args.wait)
        open_group(page, args.group, args.group_id, args.group_url)
        scroll_until(page, since, args.max_scrolls, args.pause)

        all_files = tag_files(page)
        files = [f for f in all_files if match_ext(f["text"], exts)]
        log(f"页面附件 {len(all_files)} 个，匹配 {exts} 的 {len(files)} 个。")
        if not files:
            ctx.close()
            log("没有匹配的附件。用 `probe` 看看页面结构，或换 --ext。")
            return 2

        done: list[str] = []
        failed: list[str] = []
        skipped = 0
        for pos, item in enumerate(files, 1):
            name = item["text"]
            if args.limit and len(done) >= args.limit:
                break
            target = out_dir / sanitize(name)
            if target.exists() and not args.force:
                skipped += 1
                log(f"[{pos}/{len(files)}] 已存在，跳过：{name}")
                continue
            log(f"[{pos}/{len(files)}] 下载：{name}")
            saved = None
            for attempt in (1, 2):
                try:
                    saved = download_one(page, item["idx"], name, out_dir, args.timeout)
                    break
                except Exception as exc:  # noqa: BLE001
                    log(f"  第 {attempt} 次失败：{type(exc).__name__}: {str(exc)[:120]}")
                    try:
                        close_modal(page)
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(1_000)
            if saved:
                done.append(saved.name)
            else:
                failed.append(name)
        ctx.close()

    log("\n===== 结果 =====")
    log(f"成功 {len(done)}，跳过 {skipped}，失败 {len(failed)}，目录：{out_dir}")
    for name in done:
        log(f"  + {name}")
    for name in failed:
        log(f"  - {name}")
    return 0 if not failed else 1


def post_folder_name(post: dict, used: set[str]) -> str:
    """文件夹名：日期_标题前 60 字，重名自动加序号。"""
    day = (post.get("date") or "")[:10]
    title = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", post.get("title") or "无标题")
    title = re.sub(r"\s+", " ", title).strip()[:60].strip()
    base = f"{day}_{title}" if day else title
    name, n = base, 2
    while name in used:
        name = f"{base}_{n}"
        n += 1
    used.add(name)
    return name


def find_post(posts: list[dict], key: tuple) -> dict | None:
    """按 (日期, 标题) 在最新一次抓取结果里找回同一篇帖子。"""
    date, title = key
    for post in posts:
        if post.get("date") == date and post.get("title") == title:
            return post
    for post in posts:
        if post.get("date") == date:
            return post
    return None


def already_have(folder_name: str, filename: str, root: Path, existing_roots: list[Path]) -> bool:
    """目标目录或任意 --existing 目录里已有同名文件，就认为下过了。"""
    if (root / folder_name / filename).exists():
        return True
    return any((base / folder_name / filename).exists() for base in existing_roots)


def cmd_export(args: argparse.Namespace) -> int:
    """按帖子导出：每篇一个文件夹，里面只放附件。

    实测：同一个浏览器会话里连点几次后页面会进入「点不动」的状态
    （弹窗残留 / 节点重建），所以按「尝试次数」计批次，到点就重启会话；
    失败的文件放回队列，等下一次会话重试。
    """
    since = resolve_since(args)
    exts = None if args.ext.strip() in ("*", "all", "") else [
        e.strip() for e in args.ext.split(",") if e.strip()
    ]
    root = Path(args.out).expanduser() / (args.folder_name or args.group or args.group_id or "zsxq")
    root.mkdir(parents=True, exist_ok=True)
    log(f"输出目录：{root}")
    existing_roots = [Path(e).expanduser() for e in args.existing]
    if existing_roots:
        log("已存在目录（命中则跳过）：" + "、".join(str(r) for r in existing_roots))
    words = parse_words(args.match)
    skip_words = parse_words(args.skip)
    if words:
        log(f"只下载匹配关键字的帖子：{words}（{'全部命中' if args.match_all else '任一命中'}）")

    used_names: set[str] = set()
    done, skipped, failed = 0, 0, 0
    total_bytes = 0
    manifest: list[dict] = []

    with sync_playwright() as pw:
        def start_session():
            ctx, page = launch(pw, headless=args.headless)
            page = on_zsxq(page)
            wait_for_login(page, args.wait)
            open_group(page, args.group, args.group_id, args.group_url)
            scroll_until(page, since, args.max_scrolls, args.pause)
            return ctx, page, page.evaluate(POSTS_JS)

        ctx, page, posts = start_session()
        posts = dedupe_posts(posts)
        log(f"抓到 {len(posts)} 篇帖子。")

        folder_by_key: dict[tuple, Path] = {}
        queue: list[tuple[tuple, Path, str]] = []
        matched_posts = 0
        for post in posts:
            post_date = parse_date_label(post.get("date") or "")
            if since and post_date and post_date < since:
                continue
            if not post.get("files"):
                continue
            if not post_matches(post, words, args.match_all, args.title_only):
                continue
            if skip_words and any(w.lower() in (post.get("title") or "").lower() for w in skip_words):
                continue
            matched_posts += 1
            key = ((post.get("date") or "")[:10], post.get("title"))
            folder = root / post_folder_name(post, used_names)
            folder_by_key[key] = folder
            for item in post["files"]:
                if exts and not match_ext(item["name"], exts):
                    continue
                queue.append((key, folder, item["name"]))

        log(f"待处理：{len(queue)} 个附件，分布在 {matched_posts} 篇帖子。")
        for key, folder in folder_by_key.items():
            folder.mkdir(parents=True, exist_ok=True)

        pending: list[tuple[tuple, Path, str, int]] = [(k, f, n, 0) for k, f, n in queue]
        attempts_in_session = 0
        total = len(pending)
        index = 0

        while pending:
            key, folder, name, tries = pending.pop(0)
            index += 1
            if not args.force and already_have(folder.name, sanitize(name), root, existing_roots):
                skipped += 1
                manifest.append({"folder": folder.name, "name": name, "status": "skipped"})
                continue

            if attempts_in_session >= args.batch:
                ctx.close()
                ctx, page, posts = start_session()
                attempts_in_session = 0
                log(f"  （重启会话，继续第 {index}/{total} 个）")

            current = find_post(posts, key)
            item = None
            for cand in (current or {}).get("files") or []:
                if cand["name"] == name:
                    item = cand
                    break

            saved = None
            if item is not None:
                try:
                    saved = download_one(page, item["idx"], name, folder, args.timeout)
                except Exception as exc:  # noqa: BLE001
                    log(f"    ! {name}：{type(exc).__name__}: {str(exc)[:80]}")
                    try:
                        close_modal(page)
                    except Exception:  # noqa: BLE001
                        pass
            attempts_in_session += 1

            if saved:
                done += 1
                total_bytes += saved.stat().st_size
                manifest.append({"folder": folder.name, "name": saved.name, "status": "downloaded"})
                log(f"    ✓ {saved.name}（{saved.stat().st_size / 1024:.0f} KB）  [{index}/{total}]")
            else:
                if tries < args.retries:
                    pending.append((key, folder, name, tries + 1))
                    attempts_in_session = args.batch  # 让下一轮立刻重启
                    if item is None:
                        log(f"    ↻ {name}：当前会话找不到，重启后重试")
                    else:
                        log(f"    ↻ {name}：本次失败，重启后重试（第 {tries + 1} 次）")
                else:
                    failed += 1
                    manifest.append({"folder": folder.name, "name": name, "status": "failed"})
                    log(f"    ✗ {name}：重试 {args.retries} 次仍失败")
            page.wait_for_timeout(args.delay * 1000)

        ctx.close()

    (root / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log("\n===== 汇总 =====")
    log(f"附件 {total} 个 | 新增 {done} | 跳过 {skipped} | 失败 {failed}")
    log(f"本次下载 {total_bytes / 1024 / 1024:.1f} MB → {root}")
    log(f"清单：{root / '_manifest.json'}")
    return 0 if failed == 0 else 1


def parse_words(raw: str | None) -> list[str]:
    return [w.strip() for w in (raw or "").replace("，", ",").split(",") if w.strip()]


def post_matches(
    post: dict, words: list[str], match_all: bool = False, title_only: bool = False
) -> bool:
    """标题（可选正文）里做关键字匹配；match_all 时要求全部命中。"""
    if not words:
        return True
    hay = post.get("title", "")
    if not title_only:
        hay += "\n" + post.get("text", "")
    hay = hay.lower()
    hits = [w.lower() in hay for w in words]
    return all(hits) if match_all else any(hits)


def dedupe_posts(posts: list[dict]) -> list[dict]:
    """同一篇帖子在 DOM 里偶尔重复出现，保留附件最多的那份。"""
    best: dict[tuple, dict] = {}
    for post in posts:
        key = ((post.get("date") or "")[:10], post.get("title"))
        if key not in best or len(post.get("files") or []) > len(best[key].get("files") or []):
            best[key] = post
    return list(best.values())


def cmd_search(args: argparse.Namespace) -> int:
    """只扫描不下载：列出匹配关键字的帖子，用于挑选要下载的内容。"""
    since = resolve_since(args)
    words = parse_words(args.match)
    with sync_playwright() as pw:
        ctx, page = launch(pw, headless=True)
        page = on_zsxq(page)
        wait_for_login(page, args.wait)
        open_group(page, args.group, args.group_id, args.group_url)
        scroll_until(page, since, args.max_scrolls, args.pause)
        posts = dedupe_posts(page.evaluate(POSTS_JS))
        ctx.close()

    rows = []
    for post in posts:
        post_date = parse_date_label(post.get("date") or "")
        if since and post_date and post_date < since:
            continue
        if not post_matches(post, words, args.match_all, args.title_only):
            continue
        rows.append(post)

    total_files = sum(len(p["files"]) for p in rows)
    log(f"匹配 {len(rows)} 篇帖子，共 {total_files} 个附件（关键字：{words or '无'}）：")
    for post in rows:
        log(f"  {post['date'][:10]}  [{len(post['files'])} 个]  {post['title'][:70]}")

    out = Path(args.out).expanduser() if args.out else TMP_DIR / "search.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            [{"date": p["date"], "title": p["title"], "files": [f["name"] for f in p["files"]]} for p in rows],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    log(f"清单已写入：{out}")
    return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    since = resolve_since(args)
    exts = [e.strip() for e in args.ext.split(",") if e.strip()]
    with sync_playwright() as pw:
        ctx, page = launch(pw, headless=True)
        page = on_zsxq(page)
        wait_for_login(page, args.wait)
        open_group(page, args.group, args.group_id, args.group_url)
        scroll_until(page, since, args.max_scrolls, args.pause)
        all_files = tag_files(page)
        dates = collect_dates(page)
        ctx.close()

    files = [f for f in all_files if match_ext(f["text"], exts)]
    log(f"页面附件 {len(all_files)} 个，匹配 {exts} 的 {len(files)} 个：")
    for item in files:
        log(f"  [{item['idx']}] {item['text']}")
    parsed = sorted({d for d in (parse_date_label(x["text"]) for x in dates) if d})
    if parsed:
        log(f"页面日期范围：{parsed[0]} ~ {parsed[-1]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="知识星球附件批量下载器（Playwright 本地版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="打开浏览器手动登录，保存登录态")
    p_login.add_argument("--wait", type=int, default=1800, help="等待扫码的秒数")
    p_login.set_defaults(func=cmd_login)

    p_groups = sub.add_parser("groups", help="列出已加入的群组名")
    p_groups.set_defaults(func=cmd_groups)

    p_probe = sub.add_parser("probe", help="导出页面结构，用于校准选择器")
    p_probe.add_argument("--group", help="群组名（模糊匹配）")
    p_probe.add_argument("--group-id", help="群组 id（URL 里的数字）")
    p_probe.add_argument("--group-url", help="群组完整链接")
    p_probe.add_argument("--scroll", type=int, default=0, help="导出前先滚 N 屏")
    p_probe.add_argument("--pause", type=float, default=3.0, help="导出前等待秒数")
    p_probe.add_argument("--wait", type=int, default=300, help="等待登录的秒数")
    p_probe.set_defaults(func=cmd_probe)

    def add_common(p):
        p.add_argument("--group", help="群组名（模糊匹配）")
        p.add_argument("--group-id", help="群组 id（URL 里的数字，最稳）")
        p.add_argument("--group-url", help="群组完整链接")
        p.add_argument("--days", type=int, default=7, help="只处理最近 N 天（默认 7）")
        p.add_argument("--since", help="起始日期 YYYY-MM-DD，优先于 --days")
        p.add_argument("--ext", default="pdf", help="附件扩展名，逗号分隔，默认 pdf")
        p.add_argument("--max-scrolls", type=int, default=60, help="最多滚多少屏")
        p.add_argument("--pause", type=float, default=1.2, help="每屏等待秒数")
        p.add_argument("--wait", type=int, default=600, help="等待登录的秒数")

    p_dl = sub.add_parser("download", help="按群组和日期批量下载附件")
    add_common(p_dl)
    p_dl.add_argument("--out", default=str(DEFAULT_OUT), help="下载目录（默认 ~/Downloads/zsxq）")
    p_dl.add_argument("--timeout", type=int, default=60, help="单个文件下载超时秒数")
    p_dl.add_argument("--limit", type=int, help="本次最多成功下载几个（调试用）")
    p_dl.add_argument("--force", action="store_true", help="同名文件已存在也重新下载")
    p_dl.add_argument("--headless", action="store_true", help="无头模式（看不到浏览器）")
    p_dl.set_defaults(func=cmd_download)

    p_dry = sub.add_parser("dry-run", help="只列出识别到的附件，不下载")
    add_common(p_dry)
    p_dry.set_defaults(func=cmd_dry_run)

    p_search = sub.add_parser("search", help="按关键字搜帖子，只列清单不下载")
    p_search.add_argument("--group", help="群组名（模糊匹配）")
    p_search.add_argument("--group-id", help="群组 id（URL 里的数字，最稳）")
    p_search.add_argument("--group-url", help="群组完整链接")
    p_search.add_argument("--days", type=int, default=30, help="只搜最近 N 天（默认 30）")
    p_search.add_argument("--since", help="起始日期 YYYY-MM-DD，优先于 --days")
    p_search.add_argument("--match", help="关键字，逗号分隔（标题+正文匹配）")
    p_search.add_argument("--match-all", action="store_true", help="要求全部关键字命中")
    p_search.add_argument("--title-only", action="store_true", help="只匹配标题（更精准）")
    p_search.add_argument("--max-scrolls", type=int, default=60, help="最多滚动多少批")
    p_search.add_argument("--pause", type=float, default=2.0, help="每批等待秒数")
    p_search.add_argument("--wait", type=int, default=600, help="等待登录的秒数")
    p_search.add_argument("--out", help="结果 JSON 路径，默认 .tmp/search.json")
    p_search.set_defaults(func=cmd_search)

    p_exp = sub.add_parser("export", help="按帖子导出：每篇一个文件夹，只放附件")
    p_exp.add_argument("--group", help="群组名（模糊匹配）")
    p_exp.add_argument("--group-id", help="群组 id（URL 里的数字，最稳）")
    p_exp.add_argument("--group-url", help="群组完整链接")
    p_exp.add_argument("--days", type=int, default=7, help="只处理最近 N 天（默认 7）")
    p_exp.add_argument("--since", help="起始日期 YYYY-MM-DD，优先于 --days")
    p_exp.add_argument("--ext", default="*", help="附件类型过滤，默认 * 全部")
    p_exp.add_argument("--out", default=str(DEFAULT_OUT), help="根目录（默认 downloads/）")
    p_exp.add_argument("--existing", action="append", default=[],
                       help="已下载的目录，命中同名文件则跳过（可重复，用于增量补跑）")
    p_exp.add_argument("--folder-name", help="群组子目录名，默认用群组名")
    p_exp.add_argument("--match", help="只下载匹配关键字的帖子，逗号分隔（标题+正文匹配）")
    p_exp.add_argument("--match-all", action="store_true", help="要求全部关键字命中")
    p_exp.add_argument("--title-only", action="store_true", help="只匹配标题（更精准）")
    p_exp.add_argument("--skip", help="标题含这些词的帖子跳过，逗号分隔")
    p_exp.add_argument("--max-scrolls", type=int, default=60, help="最多滚动多少批")
    p_exp.add_argument("--pause", type=float, default=2.0, help="每批等待秒数")
    p_exp.add_argument("--wait", type=int, default=600, help="等待登录的秒数")
    p_exp.add_argument("--timeout", type=int, default=90, help="单个文件下载超时秒数")
    p_exp.add_argument("--delay", type=float, default=1.0, help="每个文件之间的间隔秒数")
    p_exp.add_argument("--batch", type=int, default=3, help="每尝试 N 个文件重启一次会话（默认 3）")
    p_exp.add_argument("--retries", type=int, default=2, help="单个文件最多重试次数（默认 2）")
    p_exp.add_argument("--force", action="store_true", help="已存在也重新下载")
    p_exp.add_argument("--headless", action="store_true", help="无头模式")
    p_exp.set_defaults(func=cmd_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
