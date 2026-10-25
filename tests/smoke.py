"""离线自检：不碰真实知识星球，用本地 fixture 页面验证核心链路。

覆盖：日期解析、PDF 识别、点击 -> 弹窗 -> 下载 -> 落盘、内容保护识别。
运行：.venv\\Scripts\\python.exe tests\\smoke.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

import zsxq_dl as z  # noqa: E402

FIXTURE = (ROOT / "tests" / "fixture.html").as_uri()
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
    except AssertionError as exc:
        FAILED.append(f"{name}: {exc}")
        print(f"[FAIL] {name}: {exc}")
    except Exception as exc:  # noqa: BLE001
        FAILED.append(f"{name}: {type(exc).__name__}: {exc}")
        print(f"[ERROR] {name}: {type(exc).__name__}: {exc}")
    else:
        PASSED.append(name)
        print(f"[ok] {name}")


def test_date_parsing() -> None:
    today = date(2026, 10, 26)
    assert z.parse_date_label("今天", today) == today
    assert z.parse_date_label("昨天", today) == today - timedelta(days=1)
    assert z.parse_date_label("10-26", today) == date(2026, 10, 26)
    assert z.parse_date_label("2025-12-31", today) == date(2025, 12, 31)
    assert z.parse_date_label("12-31", today) == date(2025, 12, 31), "跨年应回溯到上一年"
    assert z.parse_date_label("垃圾文本", today) is None


def test_sanitize() -> None:
    assert z.sanitize('a/b:c*d?.pdf') == "a_b_c_d_.pdf"
    assert z.sanitize("   ") == "unnamed.pdf"


def test_browser_flow() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="zsxq-smoke-"))
    z.PROFILE_DIR = workdir / "profile"
    download_dir = workdir / "out"
    download_dir.mkdir()

    with sync_playwright() as pw:
        ctx, page = z.launch(pw, headless=True)
        try:
            page.goto(FIXTURE)

            candidates = z.tag_pdfs(page)
            assert len(candidates) == 4, f"应识别 4 个 PDF，实际 {len(candidates)}"
            names = [c["text"] for c in candidates]
            assert "2026年宏观策略.pdf" in names

            dates = [z.parse_date_label(d["text"]) for d in z.collect_dates(page)]
            dates = [d for d in dates if d]
            assert min(dates) == date(2026, 10, 20), f"最早日期应为 10-20，实际 {min(dates)}"

            saved = z.download_one(page, 0, "2026年宏观策略.pdf", download_dir, timeout_s=20)
            assert saved is not None, "正常 PDF 应下载成功"
            assert saved.exists() and saved.stat().st_size > 0, "下载文件应存在且非空"
            assert saved.read_bytes().startswith(b"%PDF"), "落盘内容应是 PDF"

            protected = z.download_one(page, 3, "会员专享研报.pdf", download_dir, timeout_s=5)
            assert protected is None, "内容保护的 PDF 应被识别并跳过"
        finally:
            ctx.close()


def main() -> int:
    check("日期解析", test_date_parsing)
    check("文件名清洗", test_sanitize)
    check("浏览器全链路", test_browser_flow)

    print(f"\n通过 {len(PASSED)}，失败 {len(FAILED)}")
    for item in FAILED:
        print(f"  - {item}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
