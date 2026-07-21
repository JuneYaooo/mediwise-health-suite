# Installation Guide - 安装指南

## 中文

> **路径注意事项（重要）**
>
> OpenClaw 的沙箱安全机制要求：skill 文件必须位于 agent 工作区（插件根目录）**内部**，
> 否则会触发 "escapes plugin root" 保护，SKILL.md 内容无法注入给 agent，脚本也无法被调用。
>
> - `clawhub install` 会把 skill 装到**执行命令时所在目录**的 `skills/` 子目录。
> - 因此，请务必先 `cd` 进入 agent 工作区目录，再运行安装命令。
> - 或者直接用 `git clone` 指定完整目标路径（见方式 2），最不容易出错。

### 方式 1：通过 ClawdHub 安装（推荐）

**必须先进入 agent 工作区目录再安装：**

```bash
# 先进入你的 OpenClaw agent 工作区（路径以实际配置为准）
cd ~/.openclaw/workspace-health

# 安装命令会将 skill 放到 ./skills/mediwise-health-suite/
clawdhub install JuneYaooo/mediwise-health-suite
```

安装完成后，运行路径检测脚本确认位置正确：

```bash
bash ~/.openclaw/workspace-health/skills/mediwise-health-suite/install-check.sh
```

### 方式 2：手动安装

#### 步骤 1：克隆仓库

```bash
# 克隆到 OpenClaw skills 目录
git clone https://github.com/JuneYaooo/mediwise-health-suite.git \
  ~/.openclaw/skills/mediwise-health-suite

# 或克隆到自定义位置
git clone https://github.com/JuneYaooo/mediwise-health-suite.git \
  ~/my-skills/mediwise-health-suite
```

#### 步骤 2：安装依赖

```bash
cd ~/.openclaw/skills/mediwise-health-suite

# 安装 Python 依赖（如果有）
pip install -r requirements.txt
```

#### 步骤 3：配置多模态视觉模型（图片识别必填）

**图片/PDF 识别（化验单、体检报告等）需要配置外部视觉模型**，否则图片类功能无法使用。

> 隐私提示：使用云端视觉提供商时，完整图片/PDF 页面会发送到所选端点，原文件可能包含姓名、身份证号、病历号等 PII。敏感材料请优先使用可信端点或本地 Ollama。

**推荐方式：通过环境变量配置（支持 .env 文件）**

复制模板文件并填入你的 API Key：

```bash
cd ~/.openclaw/skills/mediwise-health-suite
cp .env.example .env
# 编辑 .env，填入 MEDIWISE_VISION_API_KEY 等变量
```

可选的食物在线来源也在 `.env.example` 中配置：USDA 需要 API Key；Open Food Facts 免 Key，但必须显式设置 `OPENFOODFACTS_ENABLED=1`。在线食物查询仅发送食物关键词，设置 `MEDIWISE_FOOD_ONLINE_ENABLED=0` 可强制禁用全部远程食物请求。

**方案 A（国内推荐）：硅基流动 Qwen2.5-VL**

```bash
# 免费注册（含邀请奖励）：https://cloud.siliconflow.cn/i/MOlLXTYM
export MEDIWISE_VISION_PROVIDER=siliconflow
export MEDIWISE_VISION_MODEL=Qwen/Qwen2.5-VL-72B-Instruct
export MEDIWISE_VISION_API_KEY=sk-xxx
export MEDIWISE_VISION_BASE_URL=https://api.siliconflow.cn/v1
```

**方案 B（海外推荐）：Google Gemini**

```bash
export MEDIWISE_VISION_PROVIDER=openai
export MEDIWISE_VISION_MODEL=gemini-3.1-pro-preview
export MEDIWISE_VISION_API_KEY=AIzaxxx
export MEDIWISE_VISION_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
```

**方案 C：通过 setup.py 配置（内置预设，只需填 API Key）**

```bash
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts

# 查看所有内置预设（含默认模型和 Base URL）
python3 setup.py list-vision-providers

# 选择预设后只需填 --provider 和 --api-key，模型和 Base URL 自动填入
python3 setup.py set-vision --provider siliconflow --api-key sk-xxx   # 国内
python3 setup.py set-vision --provider gemini --api-key AIza-xxx      # 海外
python3 setup.py set-vision --provider ollama --api-key ollama         # 本地离线

# 验证配置
python3 setup.py test-vision
```

> 不配置视觉模型时，文本录入和基础健康记录功能仍可正常使用，只有图片/PDF 识别功能不可用。

#### 步骤 4：验证安装

重启 OpenClaw，然后测试：

```
"你好，帮我添加一个家庭成员"
```

如果 OpenClaw 响应并询问成员信息，说明安装成功。

### 方式 3：从源码安装（开发者）

```bash
# 克隆仓库
git clone https://github.com/JuneYaooo/mediwise-health-suite.git
cd mediwise-health-suite

# 创建符号链接到 OpenClaw skills 目录
ln -s $(pwd) ~/.openclaw/skills/mediwise-health-suite

# 安装开发依赖
pip install -r requirements.txt
```

### 配置（可选）

在 OpenClaw 配置文件中添加：

**位置**: `~/.openclaw/config.json` 或项目的 `.openclaw/config.json`

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

### 数据库初始化

首次执行需要数据库的命令时，系统会自动创建数据库（默认拆分为医疗与生活方式两库）。默认位置是：

```
macOS:  ~/Library/Application Support/mediwise/{medical.db,lifestyle.db}
Linux:  ${XDG_DATA_HOME:-$HOME/.local/share}/mediwise/{medical.db,lifestyle.db}
Windows: %LOCALAPPDATA%\mediwise\{medical.db,lifestyle.db}
```

可通过 `MEDIWISE_DATA_DIR`、`MEDIWISE_MEDICAL_DB_PATH` 和 `MEDIWISE_LIFESTYLE_DB_PATH` 覆盖。数据目录默认权限为 `0700`，数据库和配置文件为 `0600`。

如果需要手动初始化配置文件：

```bash
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts
python3 setup.py init
```

`setup.py init` 只创建配置；数据库仍会在第一次数据操作时自动初始化。

如果从旧版本升级（单库 `health.db`），可执行迁移命令：

```bash
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts
python3 setup.py migrate-split-db
python3 setup.py migration-status
```

### 数据备份与迁移（换设备 / 换小龙虾）

如需将数据迁移到新设备或新的 OpenClaw 实例，使用内置的备份/恢复命令：

```bash
# 旧环境：打包所有数据库和配置
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts
python3 setup.py backup --output ~/mediwise-backup.tar.gz
```

将生成的 `mediwise-backup.tar.gz` 文件传到新设备，然后在新环境执行：

```bash
# 新环境：安装 skill 后恢复数据（Schema 自动升级）
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts
python3 setup.py restore --input ~/mediwise-backup.tar.gz
```

备份会读取配置中的自定义数据库路径，并使用 SQLite 一致性快照。归档包含 `medical.db`、`lifestyle.db`、`config.json`（以及旧版 `health.db`，如存在）和 SHA-256 `manifest.json`，文件权限为 `0600`。恢复会先校验成员白名单、大小、哈希及 SQLite 完整性，再自动升级 Schema。同一数据目录不允许两个恢复进程并发执行；替换、Schema 升级或升级后完整性检查失败时会恢复原有配置、数据库和 SQLite sidecar。运行 restore 前仍须停止 OpenClaw 服务、定时同步任务和其他 SQLite 客户端。2.0.8 及更早的官方无 manifest 备份仍可恢复，但无法进行哈希校验。manifest 未签名，不提供来源真实性保证。

### 故障排查

#### 问题 1：Skills 未加载

**解决方案**：
```bash
# 检查 skills 目录
ls ~/.openclaw/skills/mediwise-health-suite

# 重启 OpenClaw
openclaw restart
```

#### 问题 2：Python 脚本执行失败

**解决方案**：
```bash
# 检查 Python 版本
python3 --version  # 应该 >= 3.8

# 检查脚本权限
chmod +x ~/.openclaw/skills/mediwise-health-suite/*/scripts/*.py
```

#### 问题 3：数据库权限错误

**解决方案**：
```bash
# 检查数据库目录权限
# Linux 默认；macOS 请改为 "$HOME/Library/Application Support/mediwise"
DATA_DIR="${MEDIWISE_DATA_DIR:-$HOME/.local/share/mediwise}"
chmod 700 "$DATA_DIR"
find "$DATA_DIR" -maxdepth 1 -type f -exec chmod 600 {} +
```

---

## English

> **Important: Install Path**
>
> OpenClaw's sandbox requires skill files to be located **inside** the agent workspace
> (plugin root directory). Installing outside triggers an "escapes plugin root" error,
> which silently prevents SKILL.md from being injected and scripts from being called.
>
> - `clawhub install` places the skill in the `skills/` subdirectory of your **current working directory**.
> - Always `cd` into your agent workspace first, or use `git clone` with the full target path (Method 2).

### Method 1: Install via ClawdHub (Recommended)

**You must `cd` into the agent workspace before installing:**

```bash
# Navigate to your OpenClaw agent workspace first
cd ~/.openclaw/workspace-health

# This installs to ./skills/mediwise-health-suite/
clawdhub install JuneYaooo/mediwise-health-suite
```

After installation, verify the path is correct:

```bash
bash ~/.openclaw/workspace-health/skills/mediwise-health-suite/install-check.sh
```

### Method 2: Manual Installation

#### Step 1: Clone Repository

```bash
# Clone to OpenClaw skills directory
git clone https://github.com/JuneYaooo/mediwise-health-suite.git \
  ~/.openclaw/skills/mediwise-health-suite

# Or clone to custom location
git clone https://github.com/JuneYaooo/mediwise-health-suite.git \
  ~/my-skills/mediwise-health-suite
```

#### Step 2: Install Dependencies

```bash
cd ~/.openclaw/skills/mediwise-health-suite

# Install Python dependencies (if any)
pip install -r requirements.txt
```

#### Step 3: Configure Multimodal Vision Model (Required for Image Recognition)

**Image/PDF recognition (lab reports, checkup reports, etc.) requires configuring an external vision model.** Without this, image-based features will not work.

> Privacy note: a cloud vision provider receives the complete image/PDF page. Source documents can contain names, government identifiers, record numbers, and other PII. Use a trusted endpoint or local Ollama for sensitive material.

**Recommended: Configure via environment variables (supports .env file)**

```bash
cd ~/.openclaw/skills/mediwise-health-suite
cp .env.example .env
# Edit .env and fill in MEDIWISE_VISION_API_KEY and related variables
```

**Option A (Recommended for China): SiliconFlow Qwen2.5-VL**

```bash
# Register free (with referral bonus): https://cloud.siliconflow.cn/i/MOlLXTYM
export MEDIWISE_VISION_PROVIDER=siliconflow
export MEDIWISE_VISION_MODEL=Qwen/Qwen2.5-VL-72B-Instruct
export MEDIWISE_VISION_API_KEY=sk-xxx
export MEDIWISE_VISION_BASE_URL=https://api.siliconflow.cn/v1
```

**Option B (Recommended internationally): Google Gemini**

```bash
export MEDIWISE_VISION_PROVIDER=openai
export MEDIWISE_VISION_MODEL=gemini-3.1-pro-preview
export MEDIWISE_VISION_API_KEY=AIzaxxx
export MEDIWISE_VISION_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
```

**Option C: Configure via setup.py (built-in presets — only API Key required)**

```bash
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts

# List all built-in presets (with default model and Base URL)
python3 setup.py list-vision-providers

# Pick a preset: --model and --base-url are auto-filled
python3 setup.py set-vision --provider siliconflow --api-key sk-xxx   # China
python3 setup.py set-vision --provider gemini --api-key AIza-xxx      # International
python3 setup.py set-vision --provider ollama --api-key ollama         # Fully offline

# Verify configuration
python3 setup.py test-vision
```

> Without a vision model, text-based entry and basic health recording still work. Only image/PDF recognition is unavailable.

#### Step 4: Verify Installation

Restart OpenClaw, then test:

```
"Hello, help me add a family member"
```

If OpenClaw responds and asks for member information, installation is successful.

### Method 3: Install from Source (Developers)

```bash
# Clone repository
git clone https://github.com/JuneYaooo/mediwise-health-suite.git
cd mediwise-health-suite

# Create symbolic link to OpenClaw skills directory
ln -s $(pwd) ~/.openclaw/skills/mediwise-health-suite

# Install development dependencies
pip install -r requirements.txt
```

### Configuration (Optional)

Add to OpenClaw configuration file:

**Location**: `~/.openclaw/config.json` or project's `.openclaw/config.json`

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

### Database Initialization

The first command that needs a database creates it automatically (split into medical and lifestyle by default). Default locations are:

```
macOS:  ~/Library/Application Support/mediwise/{medical.db,lifestyle.db}
Linux:  ${XDG_DATA_HOME:-$HOME/.local/share}/mediwise/{medical.db,lifestyle.db}
Windows: %LOCALAPPDATA%\mediwise\{medical.db,lifestyle.db}
```

Override these with `MEDIWISE_DATA_DIR`, `MEDIWISE_MEDICAL_DB_PATH`, or `MEDIWISE_LIFESTYLE_DB_PATH`. Directories default to mode `0700`; databases and config files default to `0600`.

To initialize the config file manually:

```bash
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts
python3 setup.py init
```

`setup.py init` creates configuration only. Databases are still initialized by the first data operation.

If upgrading from the legacy single database (`health.db`), run the migration:

```bash
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts
python3 setup.py migrate-split-db
python3 setup.py migration-status
```

### Data Backup and Migration (New Device / New Instance)

To migrate data to a new device or a new OpenClaw instance, use the built-in backup/restore commands:

```bash
# Old environment: pack all databases and config
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts
python3 setup.py backup --output ~/mediwise-backup.tar.gz
```

Transfer `mediwise-backup.tar.gz` to the new device, then run:

```bash
# New environment: install the skill, then restore data (schema auto-upgrades)
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts
python3 setup.py restore --input ~/mediwise-backup.tar.gz
```

Backup follows configured custom database paths and creates consistent SQLite snapshots. The archive contains `medical.db`, `lifestyle.db`, `config.json` (and legacy `health.db` when present), plus a SHA-256 `manifest.json`, and is written with mode `0600`. Restore validates the member allowlist, size, hashes, and SQLite integrity before upgrading the schema. Two restore processes cannot operate on the same data directory concurrently; replacement, schema migration, or post-migration validation failure restores the previous config, databases, and SQLite sidecars. Stop OpenClaw, scheduled sync jobs, and other SQLite clients before restoring. Official pre-2.0.9 backups without a manifest remain supported but cannot be hash-checked. The manifest is not signed and does not prove archive authenticity.

### Troubleshooting

#### Issue 1: Skills Not Loaded

**Solution**:
```bash
# Check skills directory
ls ~/.openclaw/skills/mediwise-health-suite

# Restart OpenClaw
openclaw restart
```

#### Issue 2: Python Script Execution Failed

**Solution**:
```bash
# Check Python version
python3 --version  # Should be >= 3.8

# Check script permissions
chmod +x ~/.openclaw/skills/mediwise-health-suite/*/scripts/*.py
```

#### Issue 3: Database Permission Error

**Solution**:
```bash
# Check database directory permissions
# Linux default; on macOS use "$HOME/Library/Application Support/mediwise"
DATA_DIR="${MEDIWISE_DATA_DIR:-$HOME/.local/share/mediwise}"
chmod 700 "$DATA_DIR"
find "$DATA_DIR" -maxdepth 1 -type f -exec chmod 600 {} +
```
