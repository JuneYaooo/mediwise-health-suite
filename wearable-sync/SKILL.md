---
name: wearable-sync
description: >-
  可穿戴设备数据同步。支持从华为手表、小米手环（Gadgetbridge）、Zepp 等设备导入健康数据。
  可插拔 Provider 架构，当前支持 Gadgetbridge 本地 SQLite 导入。
  Wearable device data sync. Supports importing health data from Huawei watches,
  Xiaomi bands (Gadgetbridge), Zepp devices, etc. Pluggable provider architecture,
  currently supports Gadgetbridge local SQLite import.
  关键词：手环、手表、可穿戴、设备绑定、数据同步、华为手表、小米手环、Gadgetbridge、睡眠数据、步数、设备管理。
---

# Wearable Sync - 可穿戴设备数据同步

从可穿戴设备（手环/手表）采集健康数据并写入 mediwise-health-tracker 的 health_metrics 表。

## 支持的设备/Provider

| Provider | 状态 | 数据来源 | 支持指标 |
|----------|------|----------|----------|
| Gadgetbridge | ✅ 已实现 | 本地 SQLite 导出文件 | 心率、步数、血氧、睡眠 |
| 华为 Health Kit | 🔜 Stub | REST API（需企业开发者资质） | — |
| Zepp Health | 🔜 Stub | REST API（需开发者账号） | — |
| OpenWearables | 🔜 Stub | 统一 API（暂不支持华为/小米） | — |

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

## 反模式

- **不要手动修改 Gadgetbridge 导出数据库** — 直接读取即可
- **不要频繁同步相同时间段** — 系统自动去重，但会浪费 I/O
- **不要在同步过程中删除导出文件** — 等同步完成后再操作
- **OAuth Provider（华为/Zepp）当前为 Stub** — 调用会抛出 NotImplementedError
