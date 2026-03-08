---
name: mediwise-health-suite
description: >-
  完整的家庭健康管理套件。包含健康档案管理、病程记录、用药追踪、指标监测、症状分诊、
  急救指导、多源问诊对比、健康科普、饮食追踪、体重管理、可穿戴设备同步等功能。
  支持图片识别、就医前摘要生成（文本/图片/PDF）、药物安全检索、主动健康提醒。
  Complete family health management suite with medical records, symptom triage,
  medication tracking, health monitoring, diagnosis comparison, first aid guidance,
  health education, diet tracking, weight management, and wearable device sync.
  Supports image recognition, doctor visit summary generation, drug safety search, and proactive health reminders.
version: 1.0.0
author: MediWise Team
license: MIT
homepage: https://github.com/your-username/mediwise-health-suite
repository: https://github.com/your-username/mediwise-health-suite
keywords:
  - health
  - medical
  - family
  - tracking
  - diet
  - weight
  - wearable
  - triage
  - first-aid
  - chinese
  - 健康管理
  - 医疗
  - 家庭健康
  - 饮食
  - 体重
  - 急救
---

# MediWise Health Suite - 家庭健康管理套件

一个面向个人和家庭的完整健康管理助手：平时能记、能查、能提醒；不舒服时能分诊；准备看医生时还能先帮你整理一版就医摘要，并按需导出成图片或 PDF。

## 核心能力

### 1. 家庭健康档案 (mediwise-health-tracker)
- 成员信息管理：姓名、关系、性别、出生日期、血型
- 基础病史：既往史、过敏史、联系方式、紧急联系人
- 病程记录：门诊、住院、急诊、症状、诊断、检验、影像
- 用药信息：当前在用药、历史用药、停药原因
- 日常指标：血压、血糖、心率、血氧、体温、体重等
- 查询能力：健康摘要、时间线、在用药、全家概览
- **就医前摘要**：自动整理病情、既往史、在用药，生成文本/图片/PDF

### 2. 智能健康监测 (health-monitor)
- 多级阈值告警（info/warning/urgent/emergency）
- 趋势分析与异常检测
- 自动提醒：用药提醒、复查提醒、指标测量提醒
- 每日健康简报

### 3. 医学搜索与安全 (medical-search)
- 药物安全查询：交互、禁忌、不良反应
- 疾病知识搜索
- 权威来源验证（MSD、丁香园、NMPA、Mayo Clinic等）
- 编号引用与免责声明

### 4. 症状分诊 (symptom-triage)
- 结构化问诊流程
- 危险信号识别
- 可能方向分析
- 建议就诊科室

### 5. 急救指导 (first-aid)
- 标准化急救步骤
- 常见场景覆盖：CPR、烫伤、中暑、溺水、骨折、出血、噎住等
- 清晰的操作指引

### 6. 多源问诊对比 (diagnosis-comparison)
- 多平台意见交叉验证
- 差异分析与一致意见
- 第二意见参考

### 7. 健康科普 (health-education)
- 权威科普内容推荐
- 视频、图文、社交媒体精选
- 个性化推荐（基于健康档案）

### 8. 饮食追踪 (diet-tracker)
- 每餐记录与食物条目管理
- 营养分析：热量、蛋白质、脂肪、碳水、膳食纤维
- 每日/每周营养摘要
- 热量趋势分析

### 9. 体重管理 (weight-manager)
- 目标设定：减重/增重/维持
- BMI/BMR/TDEE 计算
- 运动记录与消耗追踪
- 身体围度记录
- 热量收支分析
- 达标预测

### 10. 可穿戴设备同步 (wearable-sync)
- 支持 Gadgetbridge（小米手环、华为手表等）
- 自动同步：心率、步数、血氧、睡眠
- 可插拔 Provider 架构

### 11. 自我改进 (self-improving-agent)
- 学习记录与错误追踪
- 持续改进机制

## 快速开始

### 安装

**通过 ClawdHub（推荐）：**
```bash
clawdhub install mediwise-health-suite
```

**手动安装：**
```bash
git clone https://github.com/your-username/mediwise-health-suite.git \
  ~/.openclaw/skills/mediwise-health-suite
cd ~/.openclaw/skills/mediwise-health-suite
pip install -r requirements.txt
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

4. **症状咨询**
   ```
   "我最近老是头晕"
   ```

5. **就医前准备**
   ```
   "我准备去看医生，帮我整理一下最近的情况"
   ```

6. **饮食记录**
   ```
   "帮我记录今天早餐：牛奶一杯、面包两片、鸡蛋一个"
   ```

7. **体重管理**
   ```
   "帮我设定一个减重目标，从 70kg 减到 65kg"
   ```

## 系统要求

- **Python**: 3.8+
- **SQLite**: 3.x
- **操作系统**: Linux / macOS / Windows
- **OpenClaw**: 2026.3.0+

## 配置

在 OpenClaw 配置文件中添加（可选）：

```json
{
  "plugins": {
    "mediwise-health-suite": {
      "enableDailyBriefing": true,
      "reminderCheckInterval": 60000,
      "scriptsDir": "~/.openclaw/skills/mediwise-health-suite"
    }
  }
}
```

## 数据隐私

- 所有数据存储在本地 SQLite 数据库
- 不上传任何个人健康信息到云端
- 医学搜索使用公开的权威来源
- 支持多租户隔离（共享实例场景）

## 技术架构

- **数据库**: SQLite（共享 health.db）
- **脚本语言**: Python 3.8+
- **Skill 框架**: OpenClaw Agent Skills
- **模块化设计**: 11 个独立 skills，可按需加载

## 贡献

欢迎贡献代码、报告问题或提出建议！

请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解详情。

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 免责声明

本工具仅供健康信息记录和参考，不构成医疗建议。任何健康问题请咨询专业医生。

## 联系方式

- GitHub Issues: https://github.com/your-username/mediwise-health-suite/issues
- Email: your-email@example.com

---

**关键词**: 健康管理、医疗记录、家庭健康、症状分诊、急救指导、饮食追踪、体重管理、可穿戴设备、health management, medical records, family health, symptom triage, first aid, diet tracking, weight management, wearable devices
