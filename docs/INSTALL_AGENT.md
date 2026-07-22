# MediWise Health Suite 安装指南（给 AI Agent 读）

> [返回文档中心](README.md) · [普通用户安装指南](INSTALLATION.md)

> 这是一份让 Hermes、OpenClaw、Claude Code、Codex、WorkBuddy 等 AI Agent 代用户完成安装的执行说明。任何能够加载 Skills、访问本地文件并执行脚本的 Agent 工具都可以使用。人类用户通常不需要逐条照抄；把项目的 GitHub 仓库地址发给 AI 即可。

## 项目简介

MediWise Health Suite 是面向支持 Skills 的 AI Agent 的个人本地健康助手，包含健康档案、饮食、体重、睡眠、健康监测和可穿戴数据导入。默认使用本地 SQLite，当前公开安装流程只面向个人本地实例：一个用户可以管理自己和多位家人的档案。

仓库：<https://github.com/JuneYaooo/mediwise-health-suite>

## 安装原则

- 不向用户索要真实健康数据、账号密码或 API Key。
- 不在聊天、命令输出或日志里展示凭据。
- 不覆盖已有目录中的本地改动。
- 只配置个人本地模式，不把这一数据目录部署到群聊机器人或多人共享服务。
- 由 Agent 完成命令执行，不要求普通用户复制或运行安装、配置、检查脚本。
- 默认不为图片/PDF 另配识别服务：当前 Agent 能直接读取附件时使用其已有能力；只有明确无法读取或用户主动要求时，才配置 OCR 或可选视觉 fallback。USDA、Open Food Facts 等联网数据源仍留给用户之后显式启用。

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
- 当前工具能够加载 Skills、访问本地文件并执行脚本
- 如果使用 OpenClaw：OpenClaw 2026.3.0+

缺少依赖时，先说明缺什么，再使用当前操作系统的标准包管理方式安装；不要静默修改系统环境。

## 安装步骤

### 1. 确定当前 Agent 的 Skill 目录

先根据当前 Agent 的官方约定或现有配置，确定它实际加载的 Skills 目录。不要猜测 Hermes、Claude Code、Codex、WorkBuddy 或其他工具的固定路径；必须从当前环境中确认安装位置和加载方式。

如果当前环境是 OpenClaw，优先使用 workspace 已配置的 `skills/` 目录。无法从上下文确定时，可使用其默认位置：

```text
~/.openclaw/skills/mediwise-health-suite
```

无论使用哪一种 Agent，如果目标目录已经存在：

1. 运行 `git -C <目标目录> status --short`。
2. 有本地改动时停止，不覆盖、不 reset，告诉用户需要先处理现有改动。
3. 工作树干净且远端确认为本项目时，可以执行 `git pull --ff-only` 更新。

### 2. 安装项目

使用当前 Agent 官方支持的 Skill 安装方式，把完整仓库放入它实际加载的 Skills 目录。安装完成后，根 `SKILL.md`、六个领域 Skill 目录及其脚本必须保持完整，不能只复制单个说明文件。

OpenClaw 环境如果已安装 `clawhub`，可以在正确的 workspace 中执行：

```bash
clawhub install JuneYaooo/mediwise-health-suite
```

OpenClaw 也可以使用 Git：

```bash
git clone https://github.com/JuneYaooo/mediwise-health-suite.git \
  ~/.openclaw/skills/mediwise-health-suite
```

如果当前 OpenClaw workspace 使用其他 Skill 根目录，把最后一个路径替换为 `<当前 workspace>/skills/mediwise-health-suite`。其他 Agent 应把仓库安装到该工具实际识别的目录；不要套用 `~/.openclaw` 路径。

### 3. 安装 Python 依赖

在实际安装目录中执行：

```bash
cd <mediwise-health-suite-实际安装目录>
python3 -m pip install -r requirements.txt
```

优先使用用户已有的虚拟环境；没有虚拟环境时，不要擅自用 `sudo pip`。

### 4. 可选：配置图片/PDF fallback

当前 Agent 能直接读取用户上传的图片或 PDF 时，不配置 MediWise 视觉服务，也不以 `setup.py test-vision` 是否通过作为安装标准。Skill 可直接提取附件内容，但必须先让用户确认提取结果，再写入档案。

只有当前 Agent 明确无法读取附件、实际读取失败，或用户主动要求独立识别路径时，才配置 fallback。优先使用本地 PaddleOCR 提取图片和扫描 PDF 文字；复杂版面确需云端视觉服务时，先说明隐私影响并取得用户明确同意。不得静默启用新的云端服务。

云端视觉凭据通过客户端受保护输入、`set-vision --api-key-stdin` 或 `MEDIWISE_VISION_API_KEY` 注入。不要把 Key 放进聊天、命令参数、shell 历史或仓库；系统 keyring 可用时 MediWise 会优先存入 keyring。

当前内置 OCR 适配是 PaddleOCR。若计划使用第三方 OCR API，先确认仓库已有对应适配和测试入口；不得只保存一个项目无法调用的 API 地址后声称配置完成。

PaddleOCR 是推荐的本地图片和扫描 PDF 文字识别方案。由 Agent 完成安装，不能让普通用户复制命令。

1. 先检查当前操作系统、CPU 架构、Python 版本和现有虚拟环境。
2. 按 PaddlePaddle 官方兼容矩阵选择 CPU/GPU 版本；不要盲目覆盖用户已有的 Paddle 环境。
3. 在项目使用的同一个 Python 环境中安装兼容版本的 `paddlepaddle`、`paddleocr`、`Pillow`、`numpy` 和 `PyMuPDF`。
4. 安装后执行：

```bash
python3 mediwise-health-tracker/scripts/setup.py set-pdf-engine --engine paddleocr
python3 mediwise-health-tracker/scripts/setup.py test-paddleocr
python3 mediwise-health-tracker/scripts/setup.py test-pdf
python3 mediwise-health-tracker/scripts/setup.py test-intake --input both
```

若配置多模态 fallback，也必须依次运行 `test-vision`、`test-pdf` 和 `test-intake --input both`。图片测试与 `test-pdf` 证明 fallback 识别链路，`test-intake` 再证明结果能够进入结构化提取流程；它们都返回 `status: ok` 时，才可以声称该 fallback 可用。测试默认使用内置脱敏图片，并在临时目录生成图像型 PDF，不会写入健康数据库或仓库；也可以由 Agent 使用用户授权的脱敏附件。若当前平台没有兼容轮子、模型初始化失败或任一测试失败：

- 不破坏基础安装，也不使用 `sudo pip`。
- 把 OCR 引擎恢复为 `auto`。
- 明确报告 PaddleOCR 未启用及具体原因。
- 不把云端视觉模型悄悄打开作为替代方案。

### 5. 执行安装检查

```bash
bash install-check.sh
```

脚本会检查六个领域 Skill、共享路径工具和 Python 导入。安装在标准 `<agent-root>/skills/mediwise-health-suite` 路径时还会自动校验 OpenClaw 路径；使用自定义 OpenClaw workspace 时可传入已经确认的根目录：`bash install-check.sh --agent-root <agent-root>`。其他 Agent 不套用 OpenClaw 路径规则，只执行结构与导入检查。检查失败时，报告失败的具体阶段和命令输出摘要，不要绕过失败继续声称安装完成。

### 6. 配置个人本地模式

在实际运行 MediWise 的 Agent 环境中设置 `MEDIWISE_SINGLE_USER=1`，然后确认重载后仍然生效。

- 使用当前 Agent 已有的环境变量或配置机制持久化。
- 不要只写入一个运行时不会加载的 `.env` 文件。
- 不要要求用户自己执行 `export`、编辑配置或运行验证命令。
- 不要配置群聊、多用户共享或请求级 `owner_id` 路由。
- 如果检测到当前实例已经服务多人或群聊，停止安装并说明 MediWise 当前公开版本只支持个人本地使用。

### 7. 提示重新加载 Skills

安装完成后告诉用户：

> MediWise Health Suite 已安装并通过环境检查。请重启或重新加载当前 Agent 的 Skills，让 MediWise 生效。

同时返回：

- 实际安装路径
- Python 和 Node.js 版本
- `install-check.sh` 是否通过
- 个人本地模式是否已经生效
- 如果本次配置了图片/PDF fallback：说明采用 OCR 还是视觉服务，以及图片、扫描 PDF 和结构化解析测试是否分别通过

## 重启后的冒烟对话

让用户自己发送：

```text
帮我添加一个家庭成员，叫测试成员，是我本人
```

不要为了冒烟测试创建真实姓名或真实健康指标。测试完成后应询问用户是否删除“测试成员”。

## 可选功能

可选功能不属于基础安装：

- 图片/PDF fallback：仅在当前 Agent 无法直接读取附件或用户主动要求时配置。由配置 Agent 说明本地模型和云端模型的隐私差异，再通过安全本地输入配置；不得让用户在聊天中发送 Key。
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
4. `MEDIWISE_SINGLE_USER=1` 已写入实际运行 MediWise 的个人 Agent 环境，并在重载后验证生效。
5. 已告诉用户重启或重新加载当前 Agent 的 Skills。
6. 没有把 API Key、密码或健康数据写进仓库、聊天或测试文件。

图片/PDF fallback 不属于基础安装完成标准。若本次明确配置了 fallback，则相应的 `test-vision` 或 `test-paddleocr`、`test-pdf` 与 `test-intake --input both` 必须通过；失败时只能报告该可选能力未启用，不能影响已经通过的基础安装结论。
