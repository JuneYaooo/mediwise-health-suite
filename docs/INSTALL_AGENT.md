# MediWise Health Suite 安装指南（给 AI Agent 读）

> 这是一份让 OpenClaw、Codex、Claude Code、Cursor、Trae 等 AI 助手代用户完成安装的执行说明。人类用户通常不需要逐条照抄；把项目的 GitHub 仓库地址发给 AI 即可。

## 项目简介

MediWise Health Suite 是面向 OpenClaw 的个人本地健康助手，包含健康档案、饮食、体重、睡眠、健康监测和可穿戴数据导入。默认使用本地 SQLite，当前公开安装流程只面向个人本地实例：一个用户可以管理自己和多位家人的档案。

仓库：<https://github.com/JuneYaooo/mediwise-health-suite>

## 安装原则

- 不向用户索要真实健康数据、账号密码或 API Key。
- 不在聊天、命令输出或日志里展示凭据。
- 不覆盖已有目录中的本地改动。
- 只配置个人本地模式，不把这一数据目录部署到群聊机器人或多人共享服务。
- 由 Agent 完成命令执行，不要求普通用户复制或运行安装、配置、检查脚本。
- 安装只负责本地代码、依赖、个人模式和环境检查；视觉模型、USDA、Open Food Facts 等可选功能留给用户之后显式启用。

## 前置依赖

先检查：

```bash
git --version
python3 --version
node --version
```

最低要求：

- Python 3.8+
- Node.js 18+
- Git
- 可用的 `pip`
- OpenClaw 2026.3.0+

缺少依赖时，先说明缺什么，再使用当前操作系统的标准包管理方式安装；不要静默修改系统环境。

## 安装步骤

### 1. 确定 OpenClaw Skill 目录

优先使用当前 OpenClaw workspace 已配置的 `skills/` 目录。无法从上下文确定时，使用默认位置：

```text
~/.openclaw/skills/mediwise-health-suite
```

如果目标目录已经存在：

1. 运行 `git -C <目标目录> status --short`。
2. 有本地改动时停止，不覆盖、不 reset，告诉用户需要先处理现有改动。
3. 工作树干净且远端确认为本项目时，可以执行 `git pull --ff-only` 更新。

### 2. 安装项目

如果当前环境已安装 `clawhub`，可以在正确的 OpenClaw workspace 中执行：

```bash
clawhub install JuneYaooo/mediwise-health-suite
```

否则使用 Git：

```bash
git clone https://github.com/JuneYaooo/mediwise-health-suite.git \
  ~/.openclaw/skills/mediwise-health-suite
```

如果当前 workspace 使用其他 Skill 根目录，把最后一个路径替换为 `<当前 workspace>/skills/mediwise-health-suite`。

### 3. 安装 Python 依赖

```bash
cd ~/.openclaw/skills/mediwise-health-suite
python3 -m pip install -r requirements.txt
```

优先使用用户已有的虚拟环境；没有虚拟环境时，不要擅自用 `sudo pip`。

### 4. 配置本地 PaddleOCR

PaddleOCR 是推荐的本地图片和扫描 PDF 文字识别方案。由 Agent 完成安装，不能让普通用户复制命令。

1. 先检查当前操作系统、CPU 架构、Python 版本和现有虚拟环境。
2. 按 PaddlePaddle 官方兼容矩阵选择 CPU/GPU 版本；不要盲目覆盖用户已有的 Paddle 环境。
3. 在项目使用的同一个 Python 环境中安装兼容版本的 `paddlepaddle`、`paddleocr`、`Pillow`、`numpy` 和 `PyMuPDF`。
4. 安装后执行：

```bash
python3 mediwise-health-tracker/scripts/setup.py set-pdf-engine --engine paddleocr
python3 mediwise-health-tracker/scripts/setup.py test-paddleocr
```

只有 `test-paddleocr` 返回 `status: ok` 时，才可以告诉用户“PaddleOCR 已可用”。如果当前平台没有兼容轮子或模型初始化失败：

- 不破坏基础安装，也不使用 `sudo pip`。
- 把 OCR 引擎恢复为 `auto`。
- 明确报告 PaddleOCR 未启用及具体原因。
- 不把云端视觉模型悄悄打开作为替代方案。

### 5. 执行安装检查

```bash
bash install-check.sh
```

检查失败时，报告失败的具体阶段和命令输出摘要，不要绕过失败继续声称安装完成。

### 6. 配置个人本地模式

在当前 OpenClaw Agent 的运行时环境中设置 `MEDIWISE_SINGLE_USER=1`，然后确认重载后仍然生效。

- 使用当前 OpenClaw 已有的环境变量或 Agent 配置机制持久化。
- 不要只写入一个运行时不会加载的 `.env` 文件。
- 不要要求用户自己执行 `export`、编辑配置或运行验证命令。
- 不要配置群聊、多用户共享或请求级 `owner_id` 路由。
- 如果检测到当前实例已经服务多人或群聊，停止安装并说明 MediWise 当前公开版本只支持个人本地使用。

### 7. 提示重载 OpenClaw

安装完成后告诉用户：

> MediWise Health Suite 已安装并通过环境检查。请重启或重新加载当前 OpenClaw Agent，让新的 Skills 生效。

同时返回：

- 实际安装路径
- Python 和 Node.js 版本
- `install-check.sh` 是否通过
- 个人本地模式是否已经生效
- PaddleOCR 是否通过本地图片识别测试；未启用时给出原因

## 重启后的冒烟对话

让用户自己发送：

```text
帮我添加一个家庭成员，叫测试成员，是我本人
```

不要为了冒烟测试创建真实姓名或真实健康指标。测试完成后应询问用户是否删除“测试成员”。

## 可选功能

可选功能不属于基础安装：

- 图片/PDF 复杂理解：由配置 Agent 说明本地模型和云端模型的隐私差异，再通过安全本地输入配置 `MEDIWISE_VISION_*`；不得让用户在聊天中发送 Key。
- USDA：用户明确同意后，由配置 Agent 安全设置 `USDA_API_KEY`。
- Open Food Facts：用户明确同意后，由配置 Agent 启用；不能因为免 Key 就默认联网。
- 可穿戴导入：当前只把 Apple Health 与 Gadgetbridge 作为已验证用户流程；详细规则见 [`docs/WEARABLES.md`](./WEARABLES.md)。
- Garmin：当前是实验性接入，不作为默认配置；不得索要密码，也不得要求普通用户运行认证命令。

完整配置与隐私边界见 [`docs/INSTALLATION.md`](./INSTALLATION.md) 和仓库根目录 [`.env.example`](../.env.example)。

## 安装完成标准

以下条件全部满足才能声明安装成功：

1. 目标目录中存在根 `SKILL.md` 和六个领域 Skill 目录。
2. `python3 -m pip install -r requirements.txt` 成功，或依赖已由用户环境满足。
3. `bash install-check.sh` 返回 0。
4. 已尝试配置 PaddleOCR，并明确报告 `test-paddleocr` 的实际结果；失败时没有声称可用。
5. `MEDIWISE_SINGLE_USER=1` 已写入当前 OpenClaw 实际加载的个人 Agent 运行环境，并在重载后验证生效。
6. 已告诉用户重启或重新加载 OpenClaw。
7. 没有把 API Key、密码或健康数据写进仓库、聊天或测试文件。
