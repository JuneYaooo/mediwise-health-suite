---
name: wearable-sync
description: "Wearable device data sync: import health data from Garmin watches (Body Battery, HRV, sleep, heart rate), Apple Health, Huawei, Xiaomi (Gadgetbridge), Zepp devices. Pluggable provider architecture."
---

# Wearable Sync - 可穿戴设备数据同步

从可穿戴设备（手环/手表）采集健康数据并写入 mediwise-health-tracker 的 health_metrics 表。

## 支持的设备/Provider

| Provider | 状态 | 数据来源 | 支持指标 |
|----------|------|----------|----------|
| Gadgetbridge | ✅ 已实现 | 本地 SQLite 导出文件 | 心率、步数、血氧、睡眠 |
| Apple Health | ✅ 已实现 | export.xml / export.zip | 心率、步数、血氧、睡眠、体重、身高、体脂、血糖、血压、卡路里 |
| **Garmin Connect** | ✅ 已实现 | Garmin Connect 账号（非官方 API） | 心率、睡眠分期、HRV、身体电量、压力、步数、卡路里、血氧、活动记录 |
| 华为 Health Kit | 🔜 Stub | REST API（需企业开发者资质） | — |
| Zepp Health | 🔜 Stub | REST API（需开发者账号） | — |
| OpenWearables | 🔜 Stub | 统一 API（暂不支持华为/小米） | — |

> **强制规则**：每次调用脚本必须携带 `--owner-id`，从会话上下文获取发送者 ID（格式 `<channel>:<user_id>`，如 `feishu:ou_xxx` 或 `qqbot:12345`）。所有设备管理和同步操作均需携带，不得省略。

## Garmin Connect 接入说明

### 前置依赖

```bash
pip install garminconnect
```

> Garmin 使用非官方 API（模拟 Web 登录），无需申请开发者账号。需要用户的 Garmin Connect 账号和密码。

### 绑定流程

```bash
# 1. 添加 Garmin 设备
python3 {baseDir}/scripts/device.py add --member-id <id> --provider garmin --device-name "Garmin Fenix 7"

# 2. 配置账号（--prompt-password 交互输入，密码不经过模型）
python3 {baseDir}/scripts/device.py auth --device-id <id> \
  --username you@example.com \
  --prompt-password \
  --tokenstore /home/ubuntu/.garmin_tokens
# 终端会提示"请输入密码"，输入时不回显，密码不出现在命令行/日志/模型上下文中

# 也可通过环境变量传入（适合 CI/cron 无终端场景）
# export GARMIN_PASSWORD='yourpass'
# python3 device.py auth --device-id <id> --username you@example.com --tokenstore ...

# 3. 测试连接
python3 {baseDir}/scripts/device.py test --device-id <id>

# 4. 同步数据
python3 {baseDir}/scripts/sync.py run --device-id <id>
```

**Agent 引导规则（重要）：**

- **禁止在聊天中索要密码**：密码一旦在对话框输入，就会出现在模型上下文和服务端日志中
- 正确做法：先收集邮箱和 tokenstore 路径，然后生成一条 `device.py auth ... --prompt-password` 命令，让用户在自己的终端运行（可用 `! <命令>` 直接在会话执行），密码由终端 `getpass` 读取，全程不经过模型

**Agent 引导步骤（agent 对话中按序询问）：**

1. **确认设备名称**：请问你的佳明手表型号是？（如 Fenix 7、Forerunner 965，填写任意名称即可）
2. **收集邮箱**：你的 Garmin Connect 登录邮箱是？
3. **是否保存登录状态**：是否保存登录 token？（推荐，设置后登录一次即可，后续同步无需密码）
   - 是 → 询问 tokenstore 目录（可用默认值 `~/.garmin_tokens`）
4. **生成命令让用户自行输入密码**（不在聊天里问密码）：

   ```
   请在你的终端运行以下命令，运行后会提示输入密码（不回显，不经过我）：
   ! python3 {baseDir}/scripts/device.py auth --device-id <id> --username <邮箱> --prompt-password --tokenstore ~/.garmin_tokens
   ```

5. 命令运行成功后，调用 `device-test` 验证连接，再调用 `sync-device` 拉取近 7 天数据
   - 若返回错误含「升级库」提示，告知用户执行 `pip install --upgrade garminconnect`
   - 若返回错误含「两步验证」提示，告知用户需要在终端完成一次性验证后重试

### Agent 引导用户配置佳明的对话规则

当用户表达以下意图时，agent 应主动引导完成绑定流程：
- "我用佳明"、"我有 Garmin 手表"、"帮我绑定佳明"
- "我想同步佳明数据"、"我的 Fenix / Forerunner / Venu / Vivoactive"

**同步频率建议**：每小时最多同步一次，可通过 cron 自动定时同步。

### 支持的 Garmin 指标

| metric_type | 说明 | 数据格式 |
|---|---|---|
| `heart_rate` | 全天心率（5分钟间隔） | `"72"` |
| `sleep` | 睡眠分期汇总 | `{"duration_min":420,"deep_min":80,"light_min":210,"rem_min":100,"awake_min":30,"score":78}` |
| `hrv` | 夜间 HRV（RMSSD） | `{"rmssd":45.2,"weekly_avg":43.0,"status":"BALANCED"}` |
| `body_battery` | 身体电量（5分钟间隔） | `{"level":72,"charged":5,"drained":2}` |
| `stress` | 压力指数（3分钟间隔） | `"28"` |
| `steps` | 每日步数汇总 | `{"count":8500,"distance_m":6200,"calories":320}` |
| `calories` | 活动卡路里 | `"320"` |
| `blood_oxygen` | 血氧（SpO2，小时均值） | `"97"` |
| `weight` | 体重（kg，来自 Garmin Connect 体重记录） | `"72.5"`，extra 含 `bmi`/`bodyFat`/`muscleMass` 等（设备支持时） |
| `activity` | 运动记录 | `{"activity_type":"running","duration_sec":3600,"distance_m":10000,"avg_hr":152}` |
| `respiration` | 呼吸频率（次/分钟，睡眠期间采样，设备支持时） | `"14.5"` |
| `training_readiness` | 训练准备度评分（0-100，综合睡眠/HRV/负荷等子项） | `{"score":72,"level":"GOOD","sleep_score":80,"hrv_status":"BALANCED"}` |
| `training_status` | 训练状态（VO2 Max、有氧/无氧负荷，需设备支持） | `{"vo2_max":48.2,"status":"PRODUCTIVE","aerobic_load":1.2}` |
| `floors` | 爬楼层数（每日累计） | `{"ascended":12,"descended":10}` |
| `hydration` | 水分摄入（ml，需在 Garmin Connect App 手动记录） | `{"intake_ml":1800.0,"sweat_loss_ml":650.0}` |

### 注意事项

- Garmin 账号若开启双重验证（2FA），首次登录需要在终端手动输入验证码；配置 `tokenstore` 后后续无需重复验证。
- Garmin Connect 服务器有速率限制，建议同步频率不超过每小时一次。
- 佳明「身体电量」（Body Battery）是 Garmin 专有指标，存储为 `body_battery` 类型，可与饮食数据联合分析恢复趋势。
- 高驰（COROS）、Polar、Suunto 暂无官方 API，可通过 Strava 同步后使用 Strava provider（待实现）间接接入活动记录。

## 核心工作流

### 1. 设备绑定

用户需要先绑定设备，指定 Provider 和配置信息：

```bash
# 添加 Gadgetbridge 设备
python3 {baseDir}/scripts/device.py add --member-id <id> --provider gadgetbridge --device-name "小米手环 8"

# 配置 Gadgetbridge 导出文件路径
python3 {baseDir}/scripts/device.py auth --device-id <id> --export-path /path/to/Gadgetbridge.db

# 查看已绑定设备
python3 {baseDir}/scripts/device.py list --member-id <id>

# 测试设备连接
python3 {baseDir}/scripts/device.py test --device-id <id>

# 移除设备
python3 {baseDir}/scripts/device.py remove --device-id <id>
```

### 2. 数据同步

```bash
# 同步单个设备
python3 {baseDir}/scripts/sync.py run --device-id <id>

# 同步某成员所有设备
python3 {baseDir}/scripts/sync.py run --member-id <id>

# 同步所有活跃设备
python3 {baseDir}/scripts/sync.py run-all

# 查看同步状态
python3 {baseDir}/scripts/sync.py status --device-id <id>

# 查看同步历史
python3 {baseDir}/scripts/sync.py history --device-id <id> --limit 10
```

### 3. 定时同步

Skill 本身不运行后台进程。由 OpenClaw agent 每日定时触发，或用户手动请求时触发。

**OpenClaw 定时触发规范（agent 按此执行）：**

每日早晨 7:30 前，agent 应自动触发一次全量同步，流程如下：

1. 调用 `sync-all` 同步所有活跃设备
2. 若返回 `synced > 0`，继续触发 health-monitor 检测（见 health-monitor/SKILL.md）
3. 若有告警，合并进当日健康简报推送（见 mediwise-health-tracker/SKILL.md 的「每日简报推送规范」）
4. 若同步失败（认证错误/网络错误），**不静默忽略**，主动通知用户：
   > "今日佳明手表数据同步失败：{错误原因}，请检查网络或重新绑定设备。"

**用户手动请求时触发规范：**

当用户说"同步一下手表"、"更新健康数据"、"刷新佳明数据"等时，立即执行 `sync-device` 或 `sync-all`，同步完成后告知结果。

```bash
# 备用：cron 直接调用（不依赖 agent，适合服务器独立部署）
# 每小时整点同步一次
0 * * * * cd /path/to/wearable-sync/scripts && python3 sync.py run-all >> ~/mediwise-sync.log 2>&1
```

## 数据标准化

不同设备返回的原始数据格式各异，同步时统一转换为 health_metrics 格式：

| 设备原始字段 | metric_type | value 格式 |
|---|---|---|
| Gadgetbridge HEART_RATE | heart_rate | "72" |
| Gadgetbridge RAW_INTENSITY (steps) | steps | `{"count":8500,"distance_m":0,"calories":0}` |
| Gadgetbridge SpO2 | blood_oxygen | "98" |
| Gadgetbridge SLEEP | sleep | `{"duration_min":480,"deep_min":120,...}` |

## 去重策略

同步时按 `(member_id, metric_type, measured_at, source)` 做唯一性检查。已存在的同源同时间点数据会被跳过，并记录到 `wearable_sync_log` 中。

## Gadgetbridge 导出说明

1. 打开 Gadgetbridge App → 设置 → 数据库管理 → 导出数据库
2. 导出文件为 `Gadgetbridge` 或 `Gadgetbridge.db`（SQLite 格式）
3. 将文件传输到电脑，使用 `device.py auth --export-path` 配置路径

## Apple Health 导出说明

1. iPhone → 健康 App → 右上角头像 → 导出健康数据
2. 生成 `export.zip`（内含 `export.xml`）
3. 将文件传输到电脑，按以下步骤绑定：

```bash
# 添加 Apple Health 设备
python3 {baseDir}/scripts/device.py add --member-id <id> --provider apple_health --device-name "iPhone"

# 配置导出文件路径（支持 .xml 或 .zip）
python3 {baseDir}/scripts/device.py auth --device-id <id> --export-path /path/to/export.zip

# 同步数据
python3 {baseDir}/scripts/sync.py run --device-id <id>
```

支持指标：心率、静息心率、步数、血氧、睡眠分期、体重、身高、体脂率、血糖、血压、卡路里消耗。

### Apple Health 持续更新方案

Apple Health 导出是**手动触发的快照**，不是实时流。要实现持续监测，需要定期更新导出文件并重新同步。

**推荐流程（每日自动化）：**

```
iPhone 健康 App 导出
    → AirDrop / iCloud Drive / USB 传输到 Mac
    → 覆盖固定路径的 export.zip
    → cron 定时触发 sync.py
    → health-monitor check.py 检测异常
```

**方案一：iCloud Drive 自动同步（推荐，Mac 用户）**

1. iPhone 导出时选择保存到 iCloud Drive 固定目录（如 `iCloud Drive/HealthExports/export.zip`）
2. Mac 上 iCloud Drive 自动同步该文件
3. 配置 `--export-path` 指向本地 iCloud 同步目录：
   ```bash
   ~/Library/Mobile\ Documents/com~apple~CloudDocs/HealthExports/export.zip
   ```
4. 用户每次在 iPhone 重新导出覆盖该文件，Mac 自动同步，cron 定期执行同步

**方案二：快捷指令（Shortcuts）自动导出**

iOS「快捷指令」App 可设置每日定时自动导出健康数据并上传到固定位置：
1. 新建快捷指令 → 添加「导出健康数据」动作
2. 添加「上传文件」动作（保存到 iCloud Drive 或通过 SSH/SFTP 上传到服务器）
3. 设置「自动化」→「每天早上 7:00 运行」

**方案三：手动定期导出（最简单）**

用户每周或每天手动在 iPhone 导出一次，通过 AirDrop 传到 Mac，覆盖固定路径即可。适合数据精度要求不高的场景。

**cron 自动同步配置（配合以上任一方案）：**

```bash
# 编辑 crontab
crontab -e

# 每小时同步一次 Apple Health 数据并触发健康检测
0 * * * * cd /path/to/wearable-sync/scripts && python3 sync.py run --device-id <device-id> >> ~/mediwise-sync.log 2>&1
5 * * * * cd /path/to/health-monitor/scripts && python3 check.py run-all --window 2h >> ~/mediwise-check.log 2>&1
```

> **注意**：Apple Health 导出文件更新频率决定了数据新鲜度上限。iCloud 方案约有 5-15 分钟延迟；手动方案取决于用户导出频率。系统内置去重，重复同步同一文件不会产生重复数据。

## 反模式

- **不要手动修改 Gadgetbridge 导出数据库** — 直接读取即可
- **不要频繁同步相同时间段** — 系统自动去重，但会浪费 I/O
- **不要在同步过程中删除导出文件** — 等同步完成后再操作
- **OAuth Provider（华为/Zepp）当前为 Stub** — 调用会抛出 NotImplementedError

## Apple Health 实现依据与参考文献

### HealthKit 官方文档

| 文档 | 链接 | 用途 |
|------|------|------|
| HKQuantityTypeIdentifier 枚举 | https://developer.apple.com/documentation/healthkit/hkquantitytypeidentifier | APPLE_TYPE_MAP 中所有类型字符串的权威来源 |
| HKCategoryTypeIdentifier 枚举 | https://developer.apple.com/documentation/healthkit/hkcategorytypeidentifier | 睡眠分析类型 identifier |
| HKCategoryValueSleepAnalysis | https://developer.apple.com/documentation/healthkit/hkcategoryvaluesleepanalysis | SLEEP_VALUE_MAP int→阶段映射依据 |
| HKCorrelation（血压关联模型） | https://developer.apple.com/documentation/healthkit/hkcorrelation | 血压收缩压/舒张压配对60秒窗口依据 |
| HealthKit 数据类型总览 | https://developer.apple.com/documentation/healthkit/data_types | export.xml Record 元素结构（type/startDate/value/unit） |

### 睡眠分期 int 映射（iOS 16+）

`HKCategoryValueSleepAnalysis` 整数值含义（来源：Apple 开发者文档 + WWDC 2022 Session 10005）：

| 整数值 | 枚举名 | 映射到 |
|--------|--------|--------|
| 0 | inBed | awake |
| 1 | asleepUnspecified | awake |
| 2 | awake | awake |
| 3 | asleepCore | light_sleep |
| 4 | asleepDeep | deep_sleep |
| 5 | asleepREM | rem_sleep |

值 0-2 为原始 API，值 3-5 在 iOS 16 引入精细睡眠分期时新增。

### 单位换算依据

| 换算 | 系数 | 来源 |
|------|------|------|
| 血糖 mg/dL → mmol/L | ÷ 18.0182 | 葡萄糖摩尔质量 180.182 g/mol（SI 单位标准） |
| 身高 m → cm | × 100 | SI 基本单位定义 |
| 体重 lbs → kg | × 0.453592 | NIST 磅-千克换算定义值 |
| 血氧/体脂 fraction→% | × 100 | iOS 旧版本以小数存储（≤1.0 判断） |

### 步数聚合

Apple Health 的 `HKQuantityTypeIdentifierStepCount` 为**分段采样**（非累计），每条 Record 记录一段时间内的步数增量。日步数总计通过对同一日历日内所有采样求和得到，与 Apple Health App 显示逻辑一致。

### 大文件流式解析

Apple Health 导出文件可超过 1 GB，采用 `xml.etree.ElementTree.iterparse` + `elem.clear()` 模式以 O(1) 内存处理：
- Python 官方文档：https://docs.python.org/3/library/xml.etree.elementtree.html#xml.etree.ElementTree.iterparse
