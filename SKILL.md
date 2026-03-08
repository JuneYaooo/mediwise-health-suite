---
name: mediwise-health-suite
description: >-
  家庭健康管理套件。已实现：健康档案管理（成员、病程、用药、指标、就医摘要）、
  饮食追踪（营养分析、热量计算）、体重管理（BMI/BMR/TDEE、趋势分析）。
  待完善：健康监测、可穿戴设备同步。所有数据本地存储，保护隐私。
  Family health management suite. Implemented: health records (members, visits, medications,
  metrics, doctor visit summaries), diet tracking (nutrition analysis, calorie calculation),
  weight management (BMI/BMR/TDEE, trend analysis). To be improved: health monitoring, wearable sync.
  All data stored locally for privacy.
version: 1.0.0
author: MediWise Team
license: MIT
homepage: https://github.com/JuneYaooo/mediwise-health-suite
repository: https://github.com/JuneYaooo/mediwise-health-suite
keywords:
  - health
  - medical
  - family
  - tracking
  - diet
  - weight
  - records
  - chinese
  - 健康管理
  - 医疗
  - 家庭健康
  - 饮食
  - 体重
  - openclaw
---

# MediWise Health Suite - 家庭健康管理套件

家庭健康管理助手：记录健康数据，追踪饮食和体重，为家庭健康保驾护航。

## 核心能力

### ✅ 1. 家庭健康档案 (mediwise-health-tracker)
- 成员信息管理：姓名、关系、性别、出生日期、血型
- 基础病史：既往史、过敏史、联系方式、紧急联系人
- 病程记录：门诊、住院、急诊、症状、诊断、检验、影像
- 用药信息：当前在用药、历史用药、停药原因
- 日常指标：血压、血糖、心率、血氧、体温、体重等
- 查询能力：健康摘要、时间线、在用药、全家概览
- **就医前摘要**：自动整理病情、既往史、在用药，生成文本/图片/PDF

### ✅ 2. 饮食追踪 (diet-tracker)
- 每餐记录与食物条目管理
- 营养分析：热量、蛋白质、脂肪、碳水、膳食纤维
- 每日/每周营养摘要
- 热量趋势分析

### ✅ 3. 体重管理 (weight-manager)
- 目标设定：减重/增重/维持
- BMI/BMR/TDEE 计算
- 运动记录与消耗追踪
- 身体围度记录
- 热量收支分析
- 达标预测

### ⚠️ 4. 智能健康监测 (health-monitor) - 待完善
- 多级阈值告警（info/warning/urgent/emergency）
- 趋势分析与异常检测
- 自动提醒：用药提醒、复查提醒、指标测量提醒

### ⚠️ 5. 可穿戴设备同步 (wearable-sync) - 待完善
- 支持 Gadgetbridge（小米手环、华为手表等）
- 自动同步：心率、步数、血氧、睡眠
- 可插拔 Provider 架构

## 快速开始

### 安装

**通过 ClawdHub（推荐）：**
```bash
clawdhub install JuneYaooo/mediwise-health-suite
```

**手动安装：**
```bash
git clone https://github.com/JuneYaooo/mediwise-health-suite.git \
  ~/.openclaw/skills/mediwise-health-suite
```

### 基本使用

1. **添加家庭成员**
   ```
   "帮我添加一个家庭成员，叫张三，是我爸爸"
   ```

2. **记录健康指标**
   ```
   "帮我记录今天血压 130/85，心率 72"
   ```

3. **查看健康摘要**
   ```
   "帮我看看最近的健康情况"
   ```

4. **饮食记录**
   ```
   "帮我记录今天早餐：牛奶一杯、面包两片、鸡蛋一个"
   ```

5. **体重管理**
   ```
   "帮我设定一个减重目标，从 70kg 减到 65kg"
   ```

6. **就医前准备**
   ```
   "我准备去看医生，帮我整理一下最近的情况"
   ```

## 系统要求

- **Python**: 3.8+
- **SQLite**: 3.x
- **操作系统**: Linux / macOS / Windows
- **OpenClaw**: 2026.3.0+

## 数据隐私

- 所有数据存储在本地 SQLite 数据库
- 不上传任何个人健康信息到云端
- 支持多租户隔离（共享实例场景）

## 技术架构

- **数据库**: SQLite（共享 health.db）
- **脚本语言**: Python 3.8+
- **Skill 框架**: OpenClaw Agent Skills
- **模块化设计**: 5 个 skills（3 个已实现，2 个待完善）

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 免责声明

本工具仅供健康信息记录和参考，不构成医疗建议。任何健康问题请咨询专业医生。

---

**关键词**: 健康管理、医疗记录、家庭健康、饮食追踪、体重管理、health management, medical records, family health, diet tracking, weight management
