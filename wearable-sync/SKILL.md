---
name: wearable-sync
description: "Wearable device data sync: import health data from Huawei watches, Xiaomi bands (Gadgetbridge), Zepp devices. Pluggable provider architecture; currently supports Gadgetbridge local SQLite import."
---

# Wearable Sync - 可穿戴设备数据同步

从可穿戴设备（手环/手表）采集健康数据并写入 mediwise-health-tracker 的 health_metrics 表。

## 支持的设备/Provider

| Provider | 状态 | 数据来源 | 支持指标 |
|----------|------|----------|----------|
| Gadgetbridge | ✅ 已实现 | 本地 SQLite 导出文件 | 心率、步数、血氧、睡眠 |
| Apple Health | ✅ 已实现 | export.xml / export.zip | 心率、步数、血氧、睡眠、体重、身高、体脂、血糖、血压、卡路里 |
| 华为 Health Kit | 🔜 Stub | REST API（需企业开发者资质） | — |
| Zepp Health | 🔜 Stub | REST API（需开发者账号） | — |
| OpenWearables | 🔜 Stub | 统一 API（暂不支持华为/小米） | — |

> **强制规则**：每次调用脚本必须携带 `--owner-id`，从会话上下文获取发送者 ID（格式 `<channel>:<user_id>`，如 `feishu:ou_xxx` 或 `qqbot:12345`）。所有设备管理和同步操作均需携带，不得省略。

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

Skill 本身不运行后台进程。可通过 cron 定时调用：

```bash
# crontab 示例：每30分钟同步一次
*/30 * * * * cd /path/to/wearable-sync/scripts && python3 sync.py run-all
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
