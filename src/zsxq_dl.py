#!/usr/bin/env python3
"""知识星球 PDF 批量下载器（Playwright 本地版）。

把原技能 SKILL.md 里「靠 Claude in Chrome 扩展手动点」的流程，改成本机可直接跑的脚本：
用 Playwright 驱动本机 Edge/Chromium（独立 profile，登录一次后长期有效），
按群组 + 日期范围滚动帖子，逐个点击 PDF 附件并抓取浏览器下载。

子命令：
  login    打开浏览器，等用户手动登录知识星球，保存登录态
  probe    打开浏览器，把当前页面的结构导出到 probe/，用于校准选择器
  download 按群组/日期批量下载 PDF
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / ".browser-profile"
PROBE_DIR = ROOT / "probe"
DEFAULT_OUT = Path.home() / "Downloads" / "zsxq"
HOME_URL = "https://wx.zsxq.com/"

PDF_NAME_RE = re.compile(r"\.pdf\b", re.IGNORECASE)
INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# 在页面里找出「看起来是 PDF 附件名」的叶子节点，并打上 data-zsxq-dl 标记。
TAG_PDFS_JS = r"""
() => {
  const out = [];
  const re = /\.pdf\b/i;
  let idx = 0;
  const all = document.querySelectorAll('body *');
  for (const el of all) {
    if (el.childElementCount !== 0) continue;           // 只取叶子节点
    const t = (el.textContent || '').trim();
    if (!t || t.length > 180 || !re.test(t)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;          // 过滤隐藏节点
    el.setAttribute('data-zsxq-dl', String(idx));
    out.push({
      idx: idx,
      text: t,
      tag: el.tagName.toLowerCase(),
      cls: String(el.className || ''),
      parentCls: String(el.parentElement ? el.parentElement.className : ''),
    });
    idx += 1;
  }
  return out;
}
"""

# 收集页面上像日期的小文本，用来判断是否已经滚过目标日期。
COLLECT_DATES_JS = r"""
() => {
  const out = [];
  const re = /^(?:(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})|(\d{1,2})[-/.](\d{1,2}))$/;
  for (const el of document.querySelectorAll('div,span,time,p,a')) {
    if (el.childElementCount !== 0) continue;
    const t = (el.textContent || '').trim();
    if (!t || t.length > 10) continue;
    if (!re.test(t) && !/^(今天|昨天|前天)$/.test(t)) continue;
    out.push({
      text: t,
      cls: String(el.className || ''),
      y: Math.round(el.getBoundingClientRect().top + window.scrollY),
    });
  }
  return out;
}
"""

MODAL_TEXT_RE = re.compile(r"下载文件|下载附件")
PROTECTED_HINTS = ("请在App", "请在 App", "App内查看", "app内查看", "请在APP")


def log(msg: str) -> None:
    print(msg, flush=True)


def sanitize(name: str) -> str:
    name = INVALID_CHARS.sub("_", name).strip().strip(".")
    return name[:150] or "unnamed.pdf"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, n = path.stem, path.suffix, 1
    while True:
        candidate = path.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def launch(pw, headless: bool = False) -> tuple[BrowserContext, Page]:
    """启动带持久化 profile 的浏览器；优先用本机 Edge，失败再退回 Chromium。"""
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
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            log(f"浏览器已启动（{channel or 'chromium'}），profile: {PROFILE_DIR}")
            return ctx, page
        except Exception as exc:  # noqa: BLE001 - 依次尝试各浏览器
            errors.append(f"{channel or 'chromium'}: {exc}")
    raise SystemExit("无法启动浏览器：\n  " + "\n  ".join(errors))


def on_zsxq(page: Page) -> None:
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)


def looks_logged_out(page: Page) -> bool:
    try:
        body = page.inner_text("body", timeout=5_000)
    except PWTimeout:
        return False
    return bool(re.search(r"扫码登录|登录知识星球|微信登录", body))


def wait_for_login(page: Page, timeout_s: int = 300) -> None:
    if not looks_logged_out(page):
        return
    log("检测到未登录，请在浏览器窗口里完成登录……")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(2)
        if not looks_logged_out(page):
            log("登录成功，继续。")
            return
    raise SystemExit("等待登录超时，请重新运行并先手动登录。")


def open_group(page: Page, group: str | None, group_url: str | None) -> None:
    if group_url:
        page.goto(group_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2_000)
        return
    if not group:
        raise SystemExit("需要 --group 或 --group-url 指定目标群组。")
    log(f"在左侧列表里查找群组：{group}")
    locator = page.get_by_text(group, exact=False).first
    try:
        locator.click(timeout=15_000)
    except PWTimeout:
        raise SystemExit(
            f"没在页面上找到群组「{group}」。可以改用 --group-url 直接贴群组链接。"
        ) from None
    page.wait_for_timeout(2_500)


def tag_pdfs(page: Page) -> list[dict]:
    return page.evaluate(TAG_PDFS_JS)


def collect_dates(page: Page) -> list[dict]:
    return page.evaluate(COLLECT_DATES_JS)


def parse_date_label(text: str, today: date | None = None) -> date | None:
    today = today or date.today()
    if text in ("今天",):
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
    log(f"滚动加载帖子（最多 {max_scrolls} 屏，since={since or '不限'}）……")
    stagnant = 0
    last_height = 0
    for i in range(max_scrolls):
        page.evaluate("window.scrollBy(0, 900)")
        page.wait_for_timeout(int(pause * 1000))
        height = page.evaluate("document.body.scrollHeight")
        if height == last_height:
            stagnant += 1
            if stagnant >= 4:
                log("页面高度不再增长，停止滚动。")
                break
        else:
            stagnant = 0
            last_height = height
        if since and i >= 1:
            oldest = oldest_date_on_page(page)
            if oldest and oldest < since:
                log(f"已滚到 {oldest} 的帖子，早于 {since}，停止滚动。")
                break


def close_modal(page: Page) -> None:
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    for selector in ("[class*='close']", "button[aria-label*='关闭']"):
        try:
            page.locator(selector).first.click(timeout=1_000)
            break
        except Exception:  # noqa: BLE001 - 关不掉也不致命
            continue
    page.wait_for_timeout(400)


def download_one(page: Page, idx: int, name_hint: str, out_dir: Path, timeout_s: int) -> Path | None:
    handle = page.locator(f'[data-zsxq-dl="{idx}"]')
    handle.scroll_into_view_if_needed(timeout=5_000)
    handle.click(timeout=10_000)
    page.wait_for_timeout(1_200)

    button = page.get_by_text(MODAL_TEXT_RE).first
    try:
        button.wait_for(state="visible", timeout=8_000)
    except PWTimeout:
        body = page.inner_text("body", timeout=5_000)
        if any(hint in body for hint in PROTECTED_HINTS):
            log(f"  ! {name_hint}：该群开启了内容保护，只能手机 App 下载，跳过。")
        else:
            log(f"  ! {name_hint}：没找到「下载文件」按钮，跳过。可用 probe 校准。")
        close_modal(page)
        return None

    try:
        with page.expect_download(timeout=timeout_s * 1000) as info:
            button.click(timeout=10_000)
    except PWTimeout:
        log(f"  ! {name_hint}：点击后没有触发下载，跳过。")
        close_modal(page)
        return None

    download = info.value
    filename = sanitize(download.suggested_filename or name_hint)
    target = unique_path(out_dir / filename)
    download.save_as(str(target))
    close_modal(page)
    return target


def cmd_login(args: argparse.Namespace) -> int:
    with sync_playwright() as pw:
        ctx, page = launch(pw, headless=False)
        on_zsxq(page)
        page.wait_for_timeout(2_000)
        if looks_logged_out(page):
            log("请在浏览器中扫码/账号登录知识星球。（已登录过会直接跳过）")
        log("登录完成后回到本终端按 Enter 保存并退出……")
        input()
        ctx.close()
    log(f"登录态已保存在：{PROFILE_DIR}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx, page = launch(pw, headless=False)
        on_zsxq(page)
        log("浏览器已打开。请手动进入目标群组，滚动到能看到 PDF 帖子的位置。")
        log("准备好后回到本终端按 Enter 导出页面结构……")
        input()
        result = {
            "url": page.url,
            "title": page.title(),
            "pdf_candidates": tag_pdfs(page),
            "dates": collect_dates(page),
        }
        (PROBE_DIR / "page.html").write_text(page.content(), encoding="utf-8")
        (PROBE_DIR / "probe.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        page.screenshot(path=str(PROBE_DIR / "screen.png"), full_page=False)
        log(f"已导出：{PROBE_DIR}（page.html / probe.json / screen.png）")
        log(f"识别到 PDF 候选 {len(result['pdf_candidates'])} 个。")
        ctx.close()
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    since = None
    if args.days:
        since = date.today() - timedelta(days=args.days)
    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d").date()

    with sync_playwright() as pw:
        ctx, page = launch(pw, headless=False)
        on_zsxq(page)
        page.wait_for_timeout(2_000)
        wait_for_login(page)

        open_group(page, args.group, args.group_url)
        scroll_until(page, since, args.max_scrolls, args.pause)

        candidates = tag_pdfs(page)
        log(f"本页识别到 {len(candidates)} 个 PDF 附件。")
        if not candidates:
            log("没识别到 PDF。请运行 `python src/zsxq_dl.py probe` 导出结构后校准选择器。")
            ctx.close()
            return 2

        done: list[str] = []
        failed: list[str] = []
        for pos, cand in enumerate(candidates, 1):
            name_hint = cand["text"]
            if args.limit and pos > args.limit:
                break
            existing = out_dir / sanitize(name_hint)
            if existing.exists() and not args.force:
                log(f"[{pos}/{len(candidates)}] 已存在，跳过：{name_hint}")
                continue
            log(f"[{pos}/{len(candidates)}] 下载：{name_hint}")
            saved = None
            for attempt in (1, 2):
                try:
                    saved = download_one(page, cand["idx"], name_hint, out_dir, args.timeout)
                    break
                except Exception as exc:  # noqa: BLE001 - 单条失败不影响整体
                    log(f"  第 {attempt} 次尝试失败：{exc}")
                    try:
                        close_modal(page)
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(1_000)
            if saved:
                done.append(saved.name)
            else:
                failed.append(name_hint)

        ctx.close()

    log("\n===== 结果 =====")
    log(f"成功 {len(done)} 个，失败 {len(failed)} 个，目录：{out_dir}")
    for name in done:
        log(f"  + {name}")
    for name in failed:
        log(f"  - {name}")
    return 0 if not failed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="知识星球 PDF 批量下载器（Playwright 本地版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="打开浏览器手动登录，保存登录态")
    p_login.set_defaults(func=cmd_login)

    p_probe = sub.add_parser("probe", help="导出当前页面结构，用于校准选择器")
    p_probe.set_defaults(func=cmd_probe)

    p_dl = sub.add_parser("download", help="按群组和日期批量下载 PDF")
    p_dl.add_argument("--group", help="左侧群组列表中显示的群组名（模糊匹配）")
    p_dl.add_argument("--group-url", help="群组页面完整链接（比 --group 更稳）")
    p_dl.add_argument("--days", type=int, default=7, help="只处理最近 N 天的帖子（默认 7）")
    p_dl.add_argument("--since", help="起始日期 YYYY-MM-DD，优先级高于 --days")
    p_dl.add_argument("--out", default=str(DEFAULT_OUT), help="下载目录（默认 ~/Downloads/zsxq）")
    p_dl.add_argument("--max-scrolls", type=int, default=60, help="最多滚动多少屏（默认 60）")
    p_dl.add_argument("--pause", type=float, default=1.2, help="每屏滚动后等待秒数")
    p_dl.add_argument("--timeout", type=int, default=45, help="单个文件下载超时秒数")
    p_dl.add_argument("--limit", type=int, help="本次最多下载多少个（调试用）")
    p_dl.add_argument("--force", action="store_true", help="同名文件已存在时仍重新下载")
    p_dl.add_argument("--dry-run", action="store_true", help="只列出识别结果，不实际下载")
    p_dl.set_defaults(func=cmd_download)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "dry_run", False):
        args.func = lambda a: _dry_run(a)
    return args.func(args)


def _dry_run(args: argparse.Namespace) -> int:
    """扫描但不点击，用来确认群组/日期/文件识别是否正确。"""
    since = None
    if args.days:
        since = date.today() - timedelta(days=args.days)
    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d").date()

    with sync_playwright() as pw:
        ctx, page = launch(pw, headless=False)
        on_zsxq(page)
        page.wait_for_timeout(2_000)
        wait_for_login(page)
        open_group(page, args.group, args.group_url)
        scroll_until(page, since, args.max_scrolls, args.pause)
        candidates = tag_pdfs(page)
        dates = collect_dates(page)
        ctx.close()

    log(f"识别到 {len(candidates)} 个 PDF：")
    for cand in candidates:
        log(f"  - {cand['text']}")
    if dates:
        parsed = sorted(
            {d for d in (parse_date_label(item["text"]) for item in dates) if d}
        )
        if parsed:
            log(f"页面日期范围：{parsed[0]} ~ {parsed[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
