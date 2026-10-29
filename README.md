# 行业洞察周报

投资 / 科技 / 宏观三域的动态追踪看板，聚焦 **AI、人形机器人、脑机接口、半导体** 四个核心赛道。
全自动采集 → 分类打分 → 摘要校验 → 数据看板，部署在 GitHub Pages。

- 线上地址：**https://dai-416.github.io/industry-insight/**
- 页面：首页 / 大模型专栏 / 数据看板 / 检索 / 24 个赛道详情
- 需求文档：[行业洞察周报_PRD_v3.1.md](行业洞察周报_PRD_v3.1.md)
- 仓库：https://github.com/DAI-416/industry-insight

> **当前状态**：全链路已跑通。分类 153/153 由 Gemini 判定，摘要按重要度分档生成，
> 单次采集约 5 分钟，每 3 小时自动跑一次。
>
> **Gemini 在本环境的实测特性**（已写进 `config/llm.yml` 注释）：
> - 列模型接口 0.2s，但 `generateContent` 首字延迟达 22s，`timeout` 必须给到 90s
> - 因此必须批量调用（分类 25 条/批、摘要 12 条/批），逐条调用会跑不完
> - 偶发 `503 high demand`，靠重试与拆半重试兜底
> - 输出 token 给到 2000，低于 1000 会导致 25 条 JSON 被截断

---

## 一、五分钟本地跑通

```bash
pip install -r requirements.txt

python3 -m pipeline.run            # 采集 + 处理 + 统计 + 建站
python3 -m pipeline.run --build-only   # 只重建站点（改样式或 overrides 后用）
python3 -m pipeline.run --weeks 12     # 统计窗口（默认 12 周）

cd site && python3 -m http.server 8787
# 打开 http://127.0.0.1:8787
```

**没有 Gemini Key 也能跑**：会自动降级为「关键词规则分类 + 原文首句摘要」，全链路可通。

---

## 二、目录结构

```
config/
  taxonomy.yml     分类体系：3 域 / 25 赛道 / 4 市场 / 关键词 / 打分事件类型
  sources.yml      30 个信源，status 字段标记可用性
  filters.yml      黑名单、长度门槛、去重阈值
  llm.yml          Gemini 型号、参数、预算上限、降级策略
pipeline/
  fetch.py         P1 采集（三级 XML 容错 + 正则兜底）
  clean.py         P2 清洗 + P3 三级去重（URL / 标题相似 / 词集 Jaccard）
  classify.py      P4 分类（Gemini 优先，规则降级，置信度拦截）
  score.py         P5 五维重要度打分
  summarize.py     P6 摘要 + P7 反幻觉校验
  stats.py         P8 统计（全代码计算，不经模型）
  overrides.py     修正层：pin / recategorize / rescore / delete / add
  charts.py        自绘 SVG 图表引擎（零依赖）
  build_site.py    P9 站点生成
  run.py           编排入口
data/
  events/YYYY-Www.json   按周切分的事件库（入库）
  manual/*.md            人工补录
  overrides.yml          人工修正规则
  stats/                 看板统计产物
  raw/                   原始采集快照（不入库）
site/                    构建产物（部署目录）
```

---

## 三、部署到 GitHub Pages

### 1. 建仓库并推送

```bash
git init && git add . && git commit -m "init"
git remote add origin git@github.com:<你的账号>/<仓库名>.git
git push -u origin main
```

仓库必须是 **Public**——GitHub Free 账户的 Pages 仅对公开仓库开放。

### 2. 配置 Gemini 密钥（可选但强烈建议）

Settings → Secrets and variables → Actions → New repository secret

- Name: `GEMINI_API_KEY`
- Value: 你的 Gemini API Key（https://aistudio.google.com/apikey）

> 不配也能跑，但分类准确率会明显下降（见第五节）。

### 3. 开启 Pages

Settings → Pages → Source 选 **GitHub Actions**。

之后每次 `site/` 变更会自动部署，地址形如 `https://<账号>.github.io/<仓库名>/`。

### 4. 首次体检信源

```bash
python3 tools/check_sources.py            # 实测并回写 status
python3 tools/check_sources.py --dry-run  # 只看结果不写回
```

---

## 四、当前信源状态（实测，2026-10-29）

40 个源中 **20 个 RSS 可用**（含新增的 10 个 AI 信源）：

| 源 | 覆盖 | 级别 |
|---|---|---|
| 美联储 | 全球货币政策 | S |
| 国家统计局 | 宏观数据 | S |
| 华尔街见闻 | 全球宏观、市场 | A |
| 量子位 | AI | B |
| 日经亚洲 | 半导体供应链 | D |
| 南华早报 | 港股 / 中概科技 | D |
| IEEE Spectrum | 机器人、脑机接口、量子 | B |
| The Verge | AI、消费电子 | D |
| TechCrunch | AI 创投、融资 | D |
| SEMI | 半导体产业 | B |
| OpenAI 官方博客 | 大模型版本与能力 | B |
| Google AI 博客 | Gemini 与 AI 研究 | B |
| Google DeepMind | 前沿模型研究 | B |
| Hugging Face | 开源模型与权重发布 | B |
| The Decoder | AI 产业深度 | B |
| MarkTechPost | AI 技术快讯 | D |
| InfoQ 中文 | 国内 AI 工程实践 | B |
| MIT 科技评论 | AI 与社会 | D |
| Techmeme | 科技聚合（AI 占比高） | D |
| Simon Willison | AI 工程实践个人博客 | E |

**20 个不可用**，原因分三类：

1. **无 RSS**（中国政府网、央行、证监会、统计局外的部委、财联社、第一财经、上海证券报）：需接 RSSHub 或写 HTML 列表解析器。
2. **返回 HTML 或 404/403/500**（财新、36 氪、机器之心、智东西、集微网、虎嗅、路透社、TrendForce）：站点改了结构或加了反爬。
3. **网络超时**（证券时报、集微网、虎嗅）：境外出口访问慢或不稳定。

替换办法：编辑 `config/sources.yml`，从文件末尾的 `alternatives` 备选池取（彭博、FT、CNBC、The Robot Report、投中网、清科、港交所披露易等），跑体检确认后把 `status` 改成 `active`。

> **已知覆盖缺口**：国内官方政策源（gov.cn / pbc / csrc）全部无 RSS，所以「投资政策与监管」赛道的国内政策条目会偏少。这是当前最大的内容短板，优先级最高的后续改进项。

---

## 五、两种运行模式的差别

| | 无 Gemini Key（规则模式） | 有 Gemini Key |
|---|---|---|
| 分类 | 关键词命中打分，无命中时按信源擅长赛道兜底 | 模型判定，置信度低于 0.6 进待归类队列 |
| 摘要 | 取正文首句（截断 140 字） | 模型压缩，强制只用原文信息 |
| 准确率 | 赛道归类约 60-70%，兜底条目偏保守 | 显著提升，且能识别跨赛道的细微差别 |
| 成本 | 0 | 建议设月度上限（默认 ¥100），超限自动降级 |

规则模式下，页面会用「低置信归类」徽标标出 `confidence < 0.7` 的条目——**看到这个标就说明该条归类不可靠**。

---

## 五又四分之一、大模型专栏

独立页面 `models.html`，聚焦「模型本身」而非应用落地：

| 模块 | 内容 | 数据来源 |
|---|---|---|
| 跑分排行 | 综合智能指数 / 上下文窗口 / 输出价格三个维度，可切换 | Artificial Analysis，`tools/update_benchmarks.py` 抓取 |
| 厂商动态 | 本周被提及条数排序，显示旗舰型号与最新动态 | 本地事件库统计 |
| 本周资讯 | LLM 赛道条目流（模型版本、能力评测、厂商动作） | 信源采集 |

跑分数据每周一自动更新（`collect.yml` 内的条件步骤）。**抓取失败时保留旧文件**，页面显示「截至 X」，不会出现空白或编造数据。

## 五半、视觉体系（16-bit 像素 RPG）

| 维度 | 实现 |
|---|---|
| 调色板 | ENDESGA-32 子集，全站统一；`--accent` 黄与 `--alarm` 红为保护色，不参与任何状态化色相偏移 |
| 抖动 | 4x4 Bayer 点阵纹理（SVG data-URI），是唯一的「渐变」手段；无 opacity 羽化 |
| 边框 | ink / white / silver 三层像素框，零圆角 |
| 字体 | Silkscreen（UI 标签，全大写）+ DotGothic16（正文，保留大小写），1px 硬阴影 |
| 图标 | 8×8 字符画经 Python 转 SVG rect，最近邻放大到 32×32 |
| 动效 | 全部 `steps()` 离散帧：菜单光标 4fps 浮动 1px、抽屉摘要 40 字/秒打字机、▼ 光标闪烁 |
| 隐喻 | 页脚 SAVE SLOT 存档槽；核心关注卡为对话框（左头像 + 打字机区域） |

尺寸系统以 `--u: 2px` 为一个像素单位，所有间距、边框均为其整数倍。

**未实现的两条**（评估后判定与本产品信息结构冲突，留作后续）：
- 回合制对战视图（竞对格局）：需要成对的攻防主体，而本系统的条目是独立事件，强行配对会制造伪叙事
- 俯视大地图（产业链上下游）：需要赛道间的有向关系图谱，当前分类体系是平铺的 23 个赛道，没有上下游数据

## 六、日常维护

### 修正一条归错的条目

编辑 `data/overrides.yml`，提交后 5 分钟内生效：

```yaml
- op: recategorize
  id: evt_2026W44_a3f21c
  track: TEC-SEMI
  market: M-GL
  content_type: fact
```

五种操作：`pin`（置顶）/ `recategorize`（改分类）/ `rescore`（改分）/ `delete`（删除）/ `add`（补录）。

### 补录一条漏掉的新闻

新建 `data/manual/2026-W44.md`：

```markdown
title: 某脑机接口公司完成临床试验入组
url: https://example.com/news/123
track: TEC-BCI
market: M-A
type: fact
score: 70
summary: 一句话摘要

正文可写在这里，会被用作摘要兜底。
---
```

### 停用或新增信源

编辑 `config/sources.yml`，`status` 改 `active` / `paused`。

---

## 七、反幻觉设计（这是本项目的核心约束）

1. **无源不发布**：没有可访问原文 URL 的条目一律不进发布态。
2. **数字必须可定位**：摘要中的多位数、小数、百分数必须能在原文找到，否则自动降级为原文首句。
3. **统计不经模型**：看板所有数字由代码计算，模型没有机会编造指标。
4. **口径写死在页面上**：每张图下方标注计算方式，页脚声明「活跃度≠景气度」。
5. **AI 内容显式标注**：抽屉里显示摘要来源（模型生成 / 原文首句 / 安全降级）。

---

## 八、已知限制

- **活跃度 ≠ 景气度**：活跃度只反映报道密度。单一热点事件就能把某赛道分数拉高，不代表行业基本面变化。
- **规则分类偏保守**：无 Key 时约 4 成条目靠信源兜底归类，精度有限。
- **跨源去重未触发**：当前 10 个源内容差异大，实测合并数为 0；接入更多同质源后才会生效。
- **正文完整性依赖 RSS**：多数源只给摘要，正文不足 200 字时标 `thin`，摘要质量受限。
- **Actions cron 不准时**：高峰期可能延迟数十分钟，周报场景可接受。
- **无日期源**：日经亚洲、SEMI 的 RSS 不提供发布时间，用抓取时间兜底，时效性判断会偏乐观。

---

## 九、后续可做

1. 为 gov.cn / pbc / csrc 写 HTML 列表解析器，补上国内政策源（收益最大）。
2. 接入 Gemini 后跑 4 周，用真实数据校准赛道关键词与打分权重。
3. 增加公司名 → 赛道的映射表，改善无关键词命中时的归类。
4. 周报快照归档页（当前只有滚动 12 周窗口）。
