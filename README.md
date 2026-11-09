# finnews-bot

[![ci](https://github.com/whan98265-prog/newscollection/actions/workflows/ci.yml/badge.svg)](https://github.com/whan98265-prog/newscollection/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Dependencies](https://img.shields.io/badge/deps-4%20packages-informational)

把多个财经 RSS 源合成一份**中文 Markdown 日报**：去重、翻译、按日期归档，可推到微信/群机器人。
零数据库、零前端，单个 Python 文件，`python finnews.py` 就能跑。

```text
📡 Reuters Markets
  ✓ 取到 100 条，新增 6 条
🌐 翻译完成：新译 7 条，失败 0 条，缓存 65 条
✅ 已写入 E:\FinNews\2026\11\09\news-20261109-203356.md
📲 推送 成功 SCT46632… HTTP 200
```

## 特性

- **多源合并**：路透（Google 新闻代理）、华尔街见闻、东方财富、BBC、WSJ，源写在 YAML 里，随便加。
- **中文标题**：走 Google 免费翻译接口，本地缓存（同一句只翻一次），不花 token。
- **保留原文**：中文标题做链接，下面小字留英文原标题，核对不会被机翻带偏。
- **七天去重**：同一条新闻只出现一次；没有新条目就不落盘、不推送。
- **按日归档**：`<root>/YYYY/MM/DD/news-YYYYMMDD-HHMMSS.md`，Windows 可直接指向 `E:/FinNews`。
- **推送可选**：Server 酱（微信）、飞书/钉钉群机器人；都不配就只落盘。
- **AI 摘要可选**：配 `OPENAI_API_KEY` 自动生成 800 字晨报（DeepSeek/OpenAI 兼容接口）。
- **三种调度**：Windows 计划任务、cron、GitHub Actions（附 workflow）。

## 快速开始

```bash
git clone https://github.com/<you>/finnews-bot.git
cd finnews-bot
pip install -r requirements.txt

cp config.example.yaml config.yaml     # Windows: copy config.example.yaml config.yaml
python finnews.py --dry-run            # 先看看长什么样，不写文件不推送
python finnews.py                      # 正式跑：落盘 +（配了 key 才）推送
```

第一次运行会自动生成 `config.yaml`（如果不存在），改完再跑即可。

Windows 双击 `run.bat` 也行。

## 配置

`config.yaml` 全量说明（只列常用）：

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `max_items` | `6` | 每个源最多取几条 |
| `keep_days` | `7` | 去重记忆保留天数 |
| `output.root` | `""` | 留空写 `reports/`；填 `E:/FinNews` 则按年月日归档 |
| `output.keep_local_copy` | `false` | 是否额外在 `reports/` 留一份 |
| `translate.enabled` | `true` | 标题自动翻中文 |
| `translate.target` | `zh-CN` | 目标语言 |
| `ai.enabled` | `auto` | `auto`=有 key 才摘要 |
| `ai.base_url` | DeepSeek | 任何 OpenAI 兼容接口都行 |
| `push.serverchan_keys` | `[]` | Server 酱 SendKey，可多个 |
| `push.webhook_url` | `""` | 飞书/钉钉机器人地址 |
| `sources` | 7 条 | `category` / `name` / `url` |

密钥建议用环境变量，别写进文件：

```bash
export SERVER_CHAN_KEYS="SCTxxxx,SCTyyyy"   # 逗号分隔，优先于 config
export NEWS_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
export OPENAI_API_KEY="sk-xxx"
```

## 输出长什么样

```markdown
# 财经速递 · 2026-11-09 20:33

> 源 7/7 可用 · 抓取 42 条 · 新增 42 条 · 去重 0 条

## 路透 · 市场

- [特朗普政府对“永久”期货的拥抱给华尔街的坚定支持者敲响了风险警报](https://news.google.com/...) `11-09 11:13` — Reuters Markets
  <br><sub>原文：Trump administration's embrace of "perp" futures sets off risk alarms for Wall Street stalwarts - Reuters</sub>

## 中文财经

- [某条中文新闻](https://...) `11-09 12:00` — 华尔街见闻
```

## 关于路透社（重要）

**路透 2020 年起关闭了公开 RSS**，官网所有 ARC 出口都是 404：

```text
https://www.reuters.com/arc/outboundfeeds/rss/?outputType=xml                   -> 404
https://www.reuters.com/arc/outboundfeeds/rss/category/business/?outputType=xml -> 404
https://www.reuters.com/rssFeed/businessNews                                    -> 401
https://rsshub.app/reuters/business                                             -> 403
```

所以"把 reuters.com 填进 RSS 列表"是行不通的。本项目改用 **Google 新闻的 site: 检索**：

```text
https://news.google.com/rss/search?q=site%3Areuters.com+markets+when%3A2d&hl=en-US&gl=US&ceid=US%3Aen
```

- `site%3Areuters.com` 只要路透文章，`markets` 可换 `business` / `china` / `oil` / `fed` / `AI`
- `when%3A2d` 只要最近 2 天（`1d`/`3d`/`7d`）
- `hl` 必须是 `en-US`，换成 `zh-CN` 实测返回 0 条
- 点链接会经 Google 跳转到 reuters.com 原文

想要纯官方源只能自建 [RSSHub](https://docs.rsshub.app/)（公共实例已对路透 403）。

## 定时运行

**Windows**（推荐，静默无窗口）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_task.ps1 -Times 09:00,17:00
Get-ScheduledTask -TaskName "FinNews-*" | Format-Table TaskName,State
```

**Linux / macOS**：见 `scripts/crontab.example`。

**GitHub Actions**（不占自己的机器）：仓库开 Actions，加 Secrets `SERVER_CHAN_KEYS`（可选），
`.github/workflows/daily.yml` 会在北京时间 09:00 / 17:00 跑，日报作为 Artifact 可下载。

## 推送到微信 / 群

| 渠道 | 怎么配 | 备注 |
| --- | --- | --- |
| Server 酱（微信） | <https://sct.ftqq.com/> 取 SendKey → `push.serverchan_keys` | 免费版 5 条/天，2 次/天刚好 |
| 飞书群机器人 | 群设置 → 机器人 → 自定义 → 复制 webhook | `webhook_kind: feishu` |
| 钉钉群机器人 | 同上 | `webhook_kind: dingtalk` |
| 不推送 | 两者都留空 | 只落盘 |

推送失败会打印 Server 酱返回的 `code/message`（HTTP 200 不代表成功，额度用尽是 `40001`），落盘不受影响。

## AI 摘要（可选）

```bash
pip install openai
export OPENAI_API_KEY="sk-..."
```

`ai.enabled: auto` 时只要有 key 就会在日报顶部加一节「今日摘要」（今日主线 / 值得跟踪 / 风险与反例）。
不配 key 就是纯标题 + 译文，够用。

## 项目结构

```text
finnews-bot/
├── finnews.py                 # 主程序（抓取/翻译/渲染/推送）
├── config.example.yaml        # 配置模板（复制成 config.yaml）
├── requirements.txt
├── run.bat                    # Windows 一键运行
├── scripts/
│   ├── install_task.ps1       # 注册 Windows 计划任务
│   └── crontab.example        # Linux/macOS 定时示例
├── tests/test_core.py         # 纯函数单测（不联网）
├── .github/workflows/
│   ├── ci.yml                 # 测试
│   └── daily.yml              # 可选：云端定时
├── data/                      # 去重与翻译缓存（gitignore）
├── logs/                      # 运行日志（gitignore）
└── reports/                   # 默认输出（gitignore）
```

## 开发

```bash
python -m py_compile finnews.py
python -m unittest discover -s tests -v
```

单测只覆盖纯函数（去重键、翻译判定、摘要清洗、Markdown 渲染、目录布局），不联网，
所以 CI 里也能跑。

## 已知边界

- Google 代理给的是跳转链接，不是 reuters.com 原始 URL；正文页对爬虫 403，所以不做正文解析。
- `when:2d` 按 Google 收录时间算，偶有 1 天误差。
- 去重按链接哈希：同一新闻被不同媒体转载会各出现一次（多源印证，算特性）。
- 机翻的专有名词偶尔别扭，原文行可用于核对。
- 翻译接口是公开免费端点，量大可能被限流；已做缓存与失败降级，不会阻断出报。

## 合规与免责

本项目只读取**公开发布的 RSS**，用于个人资讯聚合；请遵守各源的服务条款与 robots 协议，
不要高频抓取或用于商业再分发。抓取到的内容版权归原媒体所有。

本项目不构成任何投资建议。

## License

[MIT](LICENSE)。思路参考了 [sgrsun3/FinNewsCollectionBot](https://github.com/sgrsun3/FinNewsCollectionBot)，
代码为本项目重写（配置化、翻译、去重、多市场源、事件驱动落盘）。

---

### English

A tiny, dependency-light news digest bot: pull multiple finance RSS feeds, de-duplicate,
translate headlines to Chinese, render a Markdown digest, archive by date, and optionally
push to WeChat (ServerChan) or Feishu/DingTalk webhooks. Single-file CLI, YAML config,
runs on Windows Task Scheduler, cron, or GitHub Actions. MIT licensed.
