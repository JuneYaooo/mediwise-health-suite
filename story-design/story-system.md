# MediWise 健康译报叙事系统

> 本文是域中立的叙事契约。它取代 `weight-card-design/style-system.md` 的通用部分；体重作为其中一个域的案例，见文末附录与 `story-design/cases/weight.md`。

## 一句话原则

一套模板集合 = **唯一视觉轮廓 × 唯一内容角色 × 唯一动作轮廓**，跨域复用。
健康分析决定「能说什么」，可用数据、用户偏好与使用场景决定「怎么说」，动作决定「按什么顺序被看见」，小概率探索负责偶尔带来惊喜。

体重不是这套系统的主题，只是第一个接入的域。任何新域接入都不得复制模板与文案，只需提供一个 adapter。

## 分层

```text
各域原始记录（medical.db / lifestyle.db）
        ↓  adapters/<domain>.py
Signal Frame IR（story-design/signal-frame.schema.json）
        ↓  shapes.py：把域状态映射为共享形状 shape
        ↓  selector.py：资格 → 场景/语气/密度 → 可用信号 → 偏好 → 防重复 → 时刻加权 → 探索
        ↓  motion.py：由 seed + 覆盖率派生 tempo / stagger / poster_time
        ↓  render/：artboard + families/*（静态海报帧 与 动画帧 同源）
单域：自包含 .svg（动态卡） / .html（预览） / .png（冻结海报帧）
        ↓  video.py：只串联各域已完成的 Signal Frame，不做跨域计算
个人综合译报：1080×1440 逐镜头 .png + 1080×1920 H.264 .mp4 + manifest / QA
```

渲染层不认识任何具体域。它只认识 Signal Frame。凡是渲染器里出现「体重」「秤面」「kg」这类词，都属于契约违规，应改为从 `lexicon` 取词。视频层同样不得按域分支：它可以串联多个完成的 frame，但只能逐域展示各自单位，不能归一化后比较、相减或生成因果叙述。

## 形状词汇（shape）

文案按 **shape** 编 key，不按域的 state 编 key。这是防止文案组合爆炸的唯一机制：模板数 × 形状数是常量，与域数量无关。

| shape | 含义 | 触发条件（由 adapter 判定） |
|---|---|---|
| `insufficient` | 记录不足以概括方向 | 趋势不可陈述 |
| `today-vs-trend-conflict` | 最新一次与长期方向相反 | 单日方向与趋势方向相反 |
| `sustained-rise` | 单日与长期同向上行 | 趋势向上且单日不冲突 |
| `sustained-fall` | 单日与长期同向下行 | 趋势向下且单日不冲突 |
| `flat-with-noise` | 长期接近水平但当日有波动 | 趋势稳定、单日超出稳定带 |
| `stable` | 单日与长期都在稳定区间 | 趋势稳定、单日在稳定带内 |
| `rebuilding` | 断记录后重新接上 | 存在 ≥5 天空档且末段已恢复记录 |
| `spotlight` | 某一域覆盖明显更高 | 覆盖率差 ≥0.35 且主导域 ≥0.5 |
| `multi-signal` | 多域已能同框比较 | ≥3 个域 `claim_allowed` |

`up` / `down` 只描述数值方向，禁止映射为成功、失败、进步、退步、达标、失守。这条约束对所有域生效，不限于体重。

## 域词表（lexicon）

每个 adapter 提供一份词表，模板文案通过插槽取词，不写死域名词。字段含义：

| 字段 | 含义 | 必填 | 上限 |
|---|---|---|---|
| `subject` | 域主体 | 是 | 12 |
| `reading` | 单次读数的称呼 | 是 | 12 |
| `unit` | 展示单位 | 是 | 8 |
| `up` / `down` | 中性方向词 | 是 | 8 |
| `series_label` | 序列图例 | 是 | 16 |
| `scope_label` | 统计口径 | 是 | 12 |
| `fold_note` | 同日折叠说明 | 否 | 24 |

八个已注册域的取词（`scope_label` 全部为「有记录日」，故不单列）：

| 域 | `subject` | `reading` | `unit` | `up` / `down` | `series_label` | `fold_note` |
|---|---|---|---|---|---|---|
| `weight` | 体重 | 秤面 | kg | 上浮 / 回落 | 每日中位数 | 同日多次取中位数 |
| `sleep` | 睡眠 | 记录时长 | 分钟 | 变长 / 变短 | 每日记录时长 | 同夜多次导入取平均 |
| `records` | 记录 | 记录动作 | 次 | 变密 / 变疏 | 每日记录次数 | 同日多次累计 |
| `vitals` | 心率 | 记录心率 | 次/分 | 走高 / 走低 | 每日中位心率 | 同日多次取中位数 |
| `intake` | 热量 | 记录热量 | 千卡 | 变多 / 变少 | 每日记录热量 | 同日多餐累计 |
| `activity` | 步数 | 记录步数 | 步 | 变多 / 变少 | 每日记录步数 | 同日多次同步取最新 |
| `adherence` | 服药记录 | 记录剂次 | 次 | 变密 / 变疏 | 每日记录剂次 | 同日多剂累计 |
| `family` | 家庭记录 | 记录人数 | 人 | 变多 / 变少 | 每日记录人数 | 同一人同日只计一次 |

同日折叠方式与卡面标记随域声明，不随模板变化：

Signal Frame 将两步分开声明：`series_meta.fold` 记录同日折叠方式，`trend.method`
只记录后续估计器 `theil_sen`。体重兼容 API 仍可返回历史复合口径
`daily_median+theil_sen`，但不得把其中的 `daily_median` 复制到 mean/sum/last/count 域。

| 域 | `SERIES_FOLD` | `LATIN_TAG` | `PRESCRIPTION_NOUN` | `COMPANIONS` |
|---|---|---|---|---|
| `weight` | `median` | WEIGHT | 减重处方 | 摄入 / 运动 / 睡眠 |
| `sleep` | `mean` | 缺省 SLEEP | 助眠处方 | 空 |
| `records` | `count` | 缺省 RECORDS | 处理方案 | 空 |
| `vitals` | `median` | VITALS | 治疗方案 | 空 |
| `intake` | `sum` | 缺省 INTAKE | 饮食方案 | 空 |
| `activity` | `last` | ACTIVITY | 运动方案 | 空 |
| `adherence` | `count` | MED-LOG | 用药方案 | 空 |
| `family` | `count` | HOUSEHOLD | 照护方案 | 空 |

`LATIN_TAG` 缺省时回落为域名大写，用于卡面 `CASE / <TAG> + LIFE`。`family` 必须显式声明：`family` 在引擎内已指模板家族（`catalog.py` 的 12×2 不变式、`.family-weather` 类名），回落会让同一个词在卡面上表示第三种含义。

`PRESCRIPTION_NOUN` 只出现在免责句「本卡不提供诊断或〇〇」里，填的是该域最容易越界的那类输出的名字。

`COMPANIONS` 目前只有 `weight` 非空。伴随轴断言「两个信号出现在同一段时间里」，其余七域留空各有其因：`vitals`、`adherence`、`family` 一旦配对就等于把生理读数、用药与身份并置；`sleep`、`intake`、`activity` 已作为 `weight` 的伴随出现，反向配对会同一对信号写两遍；`records` 的主体就是记录行为本身。留空不减模板：12 个伴随模板回落为自述口径，24 个模板全部保留。

新增域时只增词表与 adapter，不增模板、不增文案文件。

## 分析边界（全域适用）

- 未记录日不按 0 处理，任何域都不得用缺失值参与平均。
- 平均值必须带口径，写成「有记录日平均」。
- 派生量不得跨域相减（例如摄入减运动消耗不构成热量缺口），也不输出理论结果预测。
- 只说「这些变化发生在同一阶段」，不说某项变化造成了另一项变化。
- 概括门槛：日序列型域至少 3 个记录日、事件型域至少 2 个记录日；前后半段各自不足时不做阶段比较。
- 只能转述档案中已有的诊断、处方、报告标记与用户设定阈值，不产生任何处理方案。

## 内容差异契约

同一份 Signal Frame 在所有模板中保持事实一致，但不复制同一篇文案。每套模板必须持有：

- 唯一 `content_role`：先说什么、用什么物件说；
- 唯一 `layout_mode`：缩略图轮廓可辨；
- 唯一 `motion_mode`：缩略动图轮廓可辨；
- 固定 `dominant_signal`：以哪一类信号为主角。

实现层必须持续满足：

- 三类唯一性（`content_role` / `layout_mode` / `motion_mode`）全局无重复；
- 每个家族恰好 2 个变体；
- 每个 `dominant_signal` 至少 1 套模板；
- 每个已接入域在零数据下至少 1 套可用模板；
- 模板总数为偶数且 ≥24（只增不减既有表面）。

不再断言「恰好 24 套 / 恰好 12 家族」。千人千面的乘数来自
`模板 × motion_variant × palette(6) × composition(8) × 情境文案`，
而不是靠按域复制模板堆数量。目标规模 28–32 套。

### 罗盘等方向视觉的无量纲口径

方向视觉不得直接把 `trend.delta` 乘一个常数：这个数字分别可能是 kg、分钟、步、千卡或次数，直接映射会让大单位域全部撞到同一个限位。Signal Frame 因此另给 `trend.visual_strength`：Theil–Sen 成对斜率的中位数除以成对斜率绝对值的中位数，范围为 −1..1。单位在相除时消失；符号表示稳健方向，绝对值表示成对方向的一致程度，不表示健康变化的物理幅度，也不是第二个趋势估计。

renderer 只读取这一无量纲字段并使用同一角度映射，不按域分支。缺失或为零的 `trend.delta` 一律指向正北。没有该字段的旧体重分析继续走历史角度公式，以保持已经锁定的体重卡逐字节不变；所有经 Signal Frame 进入的新链路使用无量纲口径。

## 运动语法

动态卡的动作取自闭集，只有 6 个原语，便于评审与测试：

| 原语 | 作用对象 | 规则 |
|---|---|---|
| `draw` | 趋势线 | `stroke-dashoffset` 绘制，时长与序列长度成比例 |
| `settle` | 数据点 | 依次落位，**每点间隔 = 真实日期间隔** |
| `reveal` | 文字分区 | 按自媒体阅读顺序遮罩入场 |
| `breathe` | 氛围层 | 只作用于装饰，永不作用于数字 |
| `count` | 相对量 | 只滚动相对量与派生量，绝对读数不滚动，必须落在精确末值 |
| `trace` | 生成图形 | 星图、指纹、等高线按 seeded 顺序渐次生成 |

### 动画时间轴 = 日历时间轴

`settle` 的节拍必须映射真实日期间隔：断记录 5 天，动画里就停 5 拍。缺失的数据以可感知的静默呈现，不插值、不补点、不匀速摊平。这是本系统「有趣」与「诚实」的同一处来源。

### 幕结构

4 幕，6–9 秒，末尾静帧 1.2 秒后循环：

```text
第一幕 立论：阶段肖像结论先行
第二幕 证据：序列 draw + 数据点 settle + 相对量 count
第三幕 分析：完整综合分析段与因果边界
第四幕 收束：保存理由与期号
```

即动态卡是「结论先行 → 数字证明 → 完整分析 → 保存理由」这一阅读顺序的时间化，不是给静态卡加特效。

### 确定性

动作参数全部由既有 seed 派生，写入 `visual_signature`：`motion_variant`、`tempo`、`stagger_ms`、`duration_ms`、`poster_time`。相同 seed + 相同数据 → 完全相同的一段动作与逐字节相同的 SVG。

## 冻结海报帧

PNG 是默认可分享产物，必须与动画同源且稳定：

- 根节点带 `data-freeze`；
- SMIL 走 `pauseAnimations()` + `setCurrentTime(poster_time)`；
- CSS 走 `animation-play-state: paused` + 负 `animation-delay`；
- 冻结落定后才置 `window.__ready = true`，导出侧用虚拟时间预算真正等待该标志；
- 各模板的海报帧构图与接入动画前的静态构图保持一致。

## 动作安全约束

与「不推断因果」同级的两条硬约束：

**动作价值中立。** 不使用上升绿箭头、达标礼花、红绿健康暗示；`prefers-reduced-motion` 直接退化为海报帧；任何闪烁不超过 3 次/秒。

**动作不泄露脱敏内容。** 动作是新的泄漏通道：`count` 的数值区间可反推绝对读数，`settle` 的间隔在 `show_exact_date=false` 时会暴露精确日期。因此坐标轴只承载相对量，脱敏状态下节拍间隔量化到分桶。

## 阶段肖像与分享结构

卡片先用确定性规则总结「这个用户最近处在什么记录状态」，再进入模板叙事。阶段肖像不是健康评分，也不是随机鼓励语；数据不足时只说线索还在加载。

分享包装 `social_packaging` 只放大已确认的个人事实：`cover_hook`、`cover_subhook`、`proof_points`、`save_prompt`、默认脱敏 `share_caption`、`hook_mechanisms`、`clickbait: false`。不得放大风险、制造羞耻或许诺结果。

## 连续剧

偏好文件已保存最近生成的风格与累计生成次数，据此生成期号与跨期呼应（「第 7 期」「上期说 X，这期改写了吗」）。跨期对照比单张卡的花样更容易让人持续保存。

## 隐私

默认隐藏姓名、绝对读数、目标值、精确日期、用药与检验数据。偏好文件不保存任何读数、趋势、疾病、用药或卡片正文，成员 ID 先经 SHA-256 摘要。目录尝试 `0700`、文件 `0600`。

## 兼容

现有体重动作与输出结构不变：`weight-truth`、`generate-weight-card`、`generate-weight-story-card`、`select-weight-card-style`、`weight-card-preferences`、`update-weight-card-preferences` 全部保留为薄壳并转发到 `domain=weight`。抽层期间以 golden-file 摘要锁定 24 套模板的逐字节输出。

## 附录：体重作为案例

体重域的 adapter 把 8 个体重状态映射到共享 shape：

| 体重 state | shape |
|---|---|
| `insufficient` | `insufficient` |
| `daily_up_trend_down` / `daily_down_trend_up` | `today-vs-trend-conflict` |
| `sustained_up` | `sustained-rise` |
| `sustained_down` | `sustained-fall` |
| `daily_up_stable` / `daily_down_stable` | `flat-with-noise` |
| `stable` | `stable` |

分析方法保持不变：同日中位数折叠 + Theil–Sen 稳健趋势，同期并列摄入、运动、睡眠记录，不推断因果。24 套模板表、故事时刻表、记录者人格与选择系数见 `weight-card-design/style-system.md`（历史契约，继续有效）。
