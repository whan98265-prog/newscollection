"""finnews-bot：多源财经 RSS → 去重 → 中文翻译 → Markdown 日报 → 落盘 / 推送。

设计取舍：
  1. 源、条数、输出目录、推送方式全部放 config.yaml，不写死在代码里；
  2. 路透没有官方 RSS，默认用 Google 新闻的 site:reuters.com 代理源；
  3. 不爬正文（路透对爬虫 403），摘要基于标题 + RSS 摘要，够用且更稳；
  4. 标题走 Google 免费翻译接口翻成中文，结果本地缓存，不花 token；
  5. 没有新条目就不落盘、不推送，避免空日报刷屏。

用法：
    python finnews.py                 # 抓取 + 翻译 + 落盘（配了 key 则推送）
    python finnews.py --no-ai         # 不调大模型写摘要
    python finnews.py --dry-run       # 只打印，不写文件不推送
    python finnews.py --all           # 忽略去重，输出全部条目
    python finnews.py --version
"""
from __future__ import annotations

__version__ = "1.0.0"

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from urllib.parse import quote
from urllib.request import Request, urlopen

import feedparser
import pytz
import requests
import yaml

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.yaml"
STATE = ROOT / "data" / "seen.json"
REPORTS = ROOT / "reports"

# 计划任务里没有 PYTHONIOENCODING，控制台默认 GBK，emoji 会直接抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


class _Tee:
    """同时写到控制台和 logs/run.log；pythonw 下没有控制台也能留日志。"""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a", encoding="utf-8", buffering=1)
        self._out = sys.__stdout__

    def write(self, data):
        try:
            if self._out:
                self._out.write(data)
                self._out.flush()
        except Exception:  # noqa: BLE001
            pass
        self._file.write(data)

    def flush(self):
        self._file.flush()


def setup_logging(log_path: Path | None = None) -> None:
    """CLI 运行时把 stdout/stderr 同时写进 logs/run.log；库方式导入时不生效。"""
    target = log_path or (ROOT / "logs" / "run.log")
    try:
        tee = _Tee(target)
    except Exception:  # noqa: BLE001  没有写权限就只打控制台
        return
    sys.stdout = tee
    sys.stderr = tee


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


# ---------------------------------------------------------------- 基础工具
def now(tz_name: str) -> datetime:
    return datetime.now(pytz.timezone(tz_name))


def load_seen() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_seen(seen: dict, keep_days: int) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    STATE.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")


def key_of(link: str, title: str) -> str:
    raw = (link or title or "").strip()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- 翻译
CJK = re.compile(r"[\u4e00-\u9fff]")
TR_CACHE = ROOT / "data" / "translate_cache.json"


def needs_translation(text: str) -> bool:
    if not text:
        return False
    letters = sum(1 for c in text if c.isalpha())
    if letters == 0:
        return False
    return len(CJK.findall(text)) / letters < 0.3


def load_tr_cache() -> dict:
    if TR_CACHE.exists():
        try:
            return json.loads(TR_CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _google_translate(text: str, target: str = "zh-CN") -> str | None:
    url = ("https://translate.googleapis.com/translate_a/single"
           "?client=gtx&sl=auto&tl=" + target + "&dt=t&q=" + quote(text))
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out = "".join(seg[0] for seg in data[0] if seg and seg[0])
    return out.strip() or None


def _clean_title_for_tr(title: str) -> str:
    """去掉 Google 新闻加的 ' - Reuters' / ' - 路透社' 来源后缀，翻译更干净。"""
    if " - " not in title:
        return title
    head, tail = title.rsplit(" - ", 1)
    if len(tail) <= 20 and not CJK.search(tail):
        return head.strip()
    return title


def translate_items(flat: list[dict], cfg: dict) -> dict:
    """把标题/摘要翻成中文，结果按原文哈希缓存；失败保留原文。"""
    tcfg = cfg.get("translate", {}) or {}
    if str(tcfg.get("enabled", True)).lower() in ("false", "0", "no"):
        return {"done": 0, "fail": 0}
    target = tcfg.get("target", "zh-CN")
    cache = load_tr_cache()
    done = fail = 0
    for it in flat:
        for field in ("title", "summary"):
            text = it.get(field) or ""
            if not needs_translation(text):
                continue
            src_text = _clean_title_for_tr(text) if field == "title" else text
            k = hashlib.sha1(f"{target}|{src_text}".encode("utf-8")).hexdigest()
            if k in cache:
                it[f"{field}_zh"] = cache[k]
                continue
            try:
                zh = _google_translate(src_text, target)
                if zh:
                    cache[k] = zh
                    it[f"{field}_zh"] = zh
                    done += 1
                    time.sleep(0.15)
                else:
                    fail += 1
            except Exception as exc:  # noqa: BLE001
                fail += 1
                print(f"  ! 翻译失败: {str(exc)[:60]}")
    try:
        TR_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TR_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! 翻译缓存写入失败: {exc}")
    print(f"🌐 翻译完成：新译 {done} 条，失败 {fail} 条，缓存 {len(cache)} 条")
    return {"done": done, "fail": fail}


def fetch_feed(url: str, retries: int = 3, delay: float = 2.0):
    for i in range(retries):
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": UA})
            if getattr(feed, "entries", None):
                return feed
            print(f"  ! 空 feed（第 {i + 1} 次）: {url}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! 请求失败（第 {i + 1} 次）: {exc}")
        time.sleep(delay)
    return None


def entry_time(entry) -> str:
    for field in ("published_parsed", "updated_parsed"):
        ts = entry.get(field)
        if ts:
            try:
                return datetime(*ts[:6]).strftime("%m-%d %H:%M")
            except Exception:
                pass
    return ""


def entry_summary(entry, title: str = "") -> str:
    raw = entry.get("summary") or entry.get("description") or ""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = " ".join(text.split())
    core = title.rsplit(" - ", 1)[0] if " - " in title else title
    for cand in (title, core):
        if cand and text.startswith(cand):
            text = text[len(cand):].lstrip(" -—·|:：")
            break
    text = re.sub(r"\s+(Reuters|路透社)$", "", text)
    if len(text) < 12:          # 只剩标题或来源，没有有效摘要
        return ""
    return text[:220] + ("…" if len(text) > 220 else "")


# ---------------------------------------------------------------- 抓取
def collect(cfg: dict, ignore_seen: bool) -> tuple[dict, list[dict], dict]:
    seen = load_seen()
    today = datetime.now().strftime("%Y-%m-%d")
    by_category: dict[str, list[dict]] = {}
    flat: list[dict] = []
    stats = {"sources": 0, "ok": 0, "items": 0, "new": 0, "dupe": 0}

    for src in cfg.get("sources", []):
        stats["sources"] += 1
        url, name = src["url"], src.get("name") or src["url"]
        cat = src.get("category") or "未分类"
        print(f"📡 {name}")
        feed = fetch_feed(url)
        if not feed:
            print("  ✗ 放弃这个源")
            continue
        stats["ok"] += 1
        got = 0
        for entry in feed.entries[: cfg.get("max_items", 6)]:
            title = (entry.get("title") or "").strip()
            link = entry.get("link") or entry.get("id") or ""
            if not title:
                continue
            k = key_of(link, title)
            stats["items"] += 1
            if k in seen and not ignore_seen:
                stats["dupe"] += 1
                continue
            item = {
                "title": title,
                "link": link,
                "source": name,
                "category": cat,
                "time": entry_time(entry),
                "summary": entry_summary(entry, title),
            }
            by_category.setdefault(cat, []).append(item)
            flat.append(item)
            seen[k] = today
            stats["new"] += 1
            got += 1
        print(f"  ✓ 取到 {len(feed.entries)} 条，新增 {got} 条")

    return by_category, flat, seen, stats


# ---------------------------------------------------------------- AI 摘要
def build_prompt(flat: list[dict], max_chars: int) -> str:
    buf = []
    for it in flat:
        line = f"【{it['source']}】{it['title']}"
        if it["summary"]:
            line += f"\n{it['summary']}"
        buf.append(line)
    text = "\n\n".join(buf)
    return text[:max_chars]


SYSTEM_PROMPT = """你是一名专业财经新闻分析师。基于给定的新闻标题与摘要，输出一份 800 字以内的中文晨报，结构：
1) 今日主线：3-4 条，说明发生了什么、影响哪些资产/行业；
2) 值得跟踪：2-3 个未来 1-2 周可能发酵的线索；
3) 风险与反例：指出上述判断可能错在哪里。
要求：只依据给定材料，不编造数字；不确定的地方直接写"材料未提及"。"""


def ai_summary(cfg: dict, flat: list[dict]) -> str | None:
    ai = cfg.get("ai", {})
    key = os.getenv("OPENAI_API_KEY") or ai.get("api_key") or ""
    mode = str(ai.get("enabled", "auto")).lower()
    if mode == "false" or (mode == "auto" and not key):
        return None
    if not key:
        print("  ! 配置要求 AI 但没找到 OPENAI_API_KEY，跳过摘要")
        return None
    try:
        from openai import OpenAI
    except ImportError:
        print("  ! 没安装 openai 库，跳过摘要")
        return None

    client = OpenAI(api_key=key, base_url=ai.get("base_url", "https://api.deepseek.com/v1"))
    text = build_prompt(flat, int(ai.get("max_chars", 20000)))
    print(f"🧠 调用 {ai.get('model', 'deepseek-chat')}（{len(text)} 字）…")
    resp = client.chat.completions.create(
        model=ai.get("model", "deepseek-chat"),
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": text}],
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


# ---------------------------------------------------------------- 输出
def render_md(cfg: dict, by_category: dict, summary: str | None, stats: dict) -> str:
    ts = now(cfg.get("timezone", "Asia/Shanghai"))
    out = [f"# 财经速递 · {ts:%Y-%m-%d %H:%M}", ""]
    out.append(f"> 源 {stats['ok']}/{stats['sources']} 可用 · 抓取 {stats['items']} 条 · "
               f"新增 {stats['new']} 条 · 去重 {stats['dupe']} 条")
    out.append("")
    if summary:
        out += ["## 今日摘要", "", summary, "", "---", ""]
    for cat, items in by_category.items():
        if not items:
            continue
        out += [f"## {cat}", ""]
        for it in items:
            when = f" `{it['time']}`" if it["time"] else ""
            zh = it.get("title_zh")
            title = zh or it["title"]
            out.append(f"- [{title}]({it['link']}){when} — {it['source']}")
            if zh and zh != it["title"]:
                out.append(f"  <br><sub>原文：{it['title']}</sub>")
            desc = it.get("summary_zh") or it["summary"]
            if desc:
                out.append(f"  <br>{desc}")
        out.append("")
    if not by_category:
        out += ["_本轮没有新条目。_", ""]
    return "\n".join(out)


def push_serverchan(cfg: dict, title: str, content: str) -> None:
    keys = os.getenv("SERVER_CHAN_KEYS") or ",".join(cfg.get("push", {}).get("serverchan_keys", []))
    keys = [k.strip() for k in str(keys).split(",") if k.strip()]
    if not keys:
        print("ℹ️  未配置 Server 酱 key，只落盘不推送")
        return
    for key in keys:
        try:
            r = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                              data={"title": title, "desp": content}, timeout=15)
            try:
                res = r.json()
            except Exception:  # noqa: BLE001
                res = {}
            code = res.get("code")
            ok = r.ok and (code == 0 if code is not None else True)
            detail = "" if ok else f" · {res.get('message') or res.get('info') or r.text[:120]}"
            print(f"📲 推送 {'成功' if ok else '失败'} {key[:8]}… HTTP {r.status_code}{detail}")
        except Exception as exc:  # noqa: BLE001
            print(f"📲 推送异常 {key[:8]}…: {exc}")


def push_webhook(cfg: dict, title: str, content: str) -> None:
    push = cfg.get("push", {}) or {}
    url = os.getenv("NEWS_WEBHOOK_URL") or push.get("webhook_url") or ""
    if not url:
        return
    kind = (push.get("webhook_kind") or "feishu").lower()
    text = f"{title}\n\n{content}"
    if kind == "feishu":
        payload = {"msg_type": "text", "content": {"text": text[:18000]}}
    elif kind == "dingtalk":
        payload = {"msgtype": "text", "text": {"content": text[:18000]}}
    else:
        payload = {"title": title, "text": text[:18000]}
    try:
        r = requests.post(url, json=payload, timeout=15)
        print(f"🔗 webhook({kind}) {r.status_code} {r.text[:80]}")
    except Exception as exc:  # noqa: BLE001
        print(f"🔗 webhook 失败: {exc}")


# ---------------------------------------------------------------- 主流程
def out_dir(cfg: dict, ts: datetime) -> Path:
    """输出到 <root>/YYYY/MM/DD/，root 默认 E:/FinNews。"""
    root = ((cfg.get("output") or {}).get("root") or "").strip()
    base = Path(root) if root else REPORTS
    if base.drive and not Path(base.drive + "\\").exists():
        print(f"  ! {base.drive} 不可用，回退到 {REPORTS}")
        base = REPORTS
    return base / f"{ts:%Y}" / f"{ts:%m}" / f"{ts:%d}"


def load_config(path: Path | str = CONFIG) -> dict:
    """读配置；第一次运行时自动从 config.example.yaml 复制一份。"""
    p = Path(path)
    if not p.exists():
        example = ROOT / "config.example.yaml"
        if example.exists() and p == CONFIG:
            p.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"ℹ️  已生成 {p.name}（来自 config.example.yaml），按需修改后重跑")
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        raise SystemExit(f"找不到配置文件：{p}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def slot_marker(folder: Path, slot: str) -> Path:
    """同一时段（am/pm）当天只跑一次的标记文件。"""
    return folder / f".slot-{slot}"


def main() -> int:
    setup_logging()

    ap = argparse.ArgumentParser(prog="finnews", description="多源财经 RSS 中文日报")
    ap.add_argument("--config", default=str(CONFIG), help="配置文件路径")
    ap.add_argument("--no-ai", action="store_true", help="不调用大模型")
    ap.add_argument("--dry-run", action="store_true", help="只看结果，不落盘不推送")
    ap.add_argument("--all", action="store_true", help="忽略去重")
    ap.add_argument("--slot", choices=["am", "pm"], default="",
                    help="时段标记：同一时段当天只跑一次，计划任务补跑时用")
    ap.add_argument("--version", action="version", version=f"finnews-bot {__version__}")
    args = ap.parse_args()

    cfg = load_config(args.config)
    ts = now(cfg.get("timezone", "Asia/Shanghai"))
    folder = out_dir(cfg, ts)

    if args.slot and slot_marker(folder, args.slot).exists():
        print(f"ℹ️  {ts:%Y-%m-%d} 的 {args.slot} 时段已推送过，跳过（补跑任务不必重复劳动）")
        return 0

    by_category, flat, seen, stats = collect(cfg, ignore_seen=args.all)

    translate_items(flat, cfg)

    summary = None
    if not args.no_ai and flat:
        try:
            summary = ai_summary(cfg, flat)
        except Exception as exc:  # noqa: BLE001
            print(f"! AI 摘要失败（继续输出标题）: {exc}")

    md = render_md(cfg, by_category, summary, stats)

    if args.dry_run:
        print("\n" + "=" * 60 + "\n" + md)
        return 0

    if not flat and not args.all:
        print("ℹ️  没有新条目，跳过落盘（要强制输出全量用 --all）")
        if args.slot:
            folder.mkdir(parents=True, exist_ok=True)
            slot_marker(folder, args.slot).write_text(ts.isoformat(), encoding="utf-8")
        return 0
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"news-{ts:%Y%m%d-%H%M%S}.md"
    path.write_text(md, encoding="utf-8")
    print(f"✅ 已写入 {path}")

    if str((cfg.get("output") or {}).get("keep_local_copy", "false")).lower() in ("true", "1", "yes"):
        REPORTS.mkdir(parents=True, exist_ok=True)
        (REPORTS / path.name).write_text(md, encoding="utf-8")

    save_seen(seen, int(cfg.get("keep_days", 7)))
    push_serverchan(cfg, f"📌 {ts:%Y-%m-%d} 财经速递 · {len(flat)} 条", md)
    push_webhook(cfg, f"📌 {ts:%Y-%m-%d} 财经速递 · {len(flat)} 条", md)
    if args.slot:
        slot_marker(folder, args.slot).write_text(ts.isoformat(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
