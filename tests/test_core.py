"""纯函数单测：不联网、不落盘（除临时目录）。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import finnews  # noqa: E402


class TestKeys(unittest.TestCase):
    def test_key_stable_and_short(self):
        a = finnews.key_of("https://example.com/a", "标题")
        b = finnews.key_of("https://example.com/a", "另一个标题")
        self.assertEqual(a, b)          # 有链接时只看链接
        self.assertEqual(len(a), 16)
        self.assertNotEqual(a, finnews.key_of("https://example.com/b", "标题"))

    def test_key_falls_back_to_title(self):
        self.assertEqual(finnews.key_of("", "只有标题"), finnews.key_of("", "只有标题"))


class TestTranslationHelpers(unittest.TestCase):
    def test_needs_translation(self):
        self.assertTrue(finnews.needs_translation("Stocks rally on rate cut hopes"))
        self.assertFalse(finnews.needs_translation("美股因降息预期上涨"))
        self.assertFalse(finnews.needs_translation(""))
        self.assertFalse(finnews.needs_translation("2026-11-09"))

    def test_clean_title_suffix(self):
        self.assertEqual(finnews._clean_title_for_tr("Oil jumps - Reuters"), "Oil jumps")
        self.assertEqual(finnews._clean_title_for_tr("油价上涨 - 路透社"), "油价上涨 - 路透社")
        self.assertEqual(finnews._clean_title_for_tr("No suffix here"), "No suffix here")


class TestEntrySummary(unittest.TestCase):
    def test_strip_html_and_duplicate_title(self):
        entry = {"summary": "<p>Fed holds rates &amp; signals patience</p>"}
        out = finnews.entry_summary(entry, "Fed holds rates - Reuters")
        self.assertEqual(out, "& signals patience")
        self.assertNotIn("<p>", out)
        self.assertNotIn("Fed holds rates", out)

    def test_too_short_returns_empty(self):
        self.assertEqual(finnews.entry_summary({"summary": "<b>Reuters</b>"}, "x"), "")

    def test_missing_summary(self):
        self.assertEqual(finnews.entry_summary({}, "t"), "")


class TestRender(unittest.TestCase):
    def test_markdown_shape(self):
        cfg = {"timezone": "Asia/Shanghai"}
        by_cat = {"路透 · 市场": [{
            "title": "Oil jumps - Reuters",
            "title_zh": "油价大涨",
            "link": "https://example.com/1",
            "source": "Reuters Markets",
            "time": "11-09 08:00",
            "summary": "",
        }]}
        stats = {"sources": 1, "ok": 1, "items": 1, "new": 1, "dupe": 0}
        md = finnews.render_md(cfg, by_cat, "摘要内容", stats)
        self.assertIn("# 财经速递", md)
        self.assertIn("[油价大涨](https://example.com/1)", md)
        self.assertIn("原文：Oil jumps - Reuters", md)
        self.assertIn("Reuters Markets", md)
        self.assertIn("## 今日摘要", md)
        self.assertIn("源 1/1 可用", md)

    def test_empty_run(self):
        md = finnews.render_md({}, {}, None, {"sources": 0, "ok": 0, "items": 0, "new": 0, "dupe": 0})
        self.assertIn("没有新条目", md)


class TestOutDir(unittest.TestCase):
    def test_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"output": {"root": tmp}}
            d = finnews.out_dir(cfg, datetime(2026, 11, 9, 9, 0))
            self.assertEqual(d, Path(tmp) / "2026" / "11" / "09")

    def test_empty_root_uses_reports(self):
        d = finnews.out_dir({}, datetime(2026, 1, 2))
        self.assertEqual(d.name, "02")
        self.assertEqual(d.parent.name, "01")
        self.assertEqual(d.parent.parent.name, "2026")


if __name__ == "__main__":
    unittest.main()
