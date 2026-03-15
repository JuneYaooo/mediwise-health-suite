# Installation Guide - 安装指南

## 中文

### 方式 1：通过 ClawdHub 安装（推荐）

这是最简单的安装方式：

```bash
clawdhub install mediwise-health-suite
```

安装完成后，OpenClaw 会自动加载所有 skills。

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

**推荐方式：通过环境变量配置（支持 .env 文件）**

复制模板文件并填入你的 API Key：

```bash
cd ~/.openclaw/skills/mediwise-health-suite
cp .env.example .env
# 编辑 .env，填入 MEDIWISE_VISION_API_KEY 等变量
```

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

**方案 C：通过 setup.py 配置（保存到 config.json）**

```bash
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts
python3 setup.py set-vision \
  --provider siliconflow \
  --model Qwen/Qwen2.5-VL-72B-Instruct \
  --api-key sk-xxx \
  --base-url https://api.siliconflow.cn/v1
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

首次使用时，系统会自动创建数据库（默认拆分为医疗与生活方式两库）：

```
~/.openclaw/skills/mediwise-health-suite/data/medical.db
~/.openclaw/skills/mediwise-health-suite/data/lifestyle.db
```

如果需要手动初始化：

```bash
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts
python3 setup.py init
```

如果从旧版本升级（单库 `health.db`），可执行迁移命令：

```bash
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts
python3 setup.py migrate-split-db
python3 setup.py migration-status
```

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
mkdir -p ~/.openclaw/skills/mediwise-health-suite/data
chmod 755 ~/.openclaw/skills/mediwise-health-suite/data
```

---

## English

### Method 1: Install via ClawdHub (Recommended)

This is the easiest way:

```bash
clawdhub install mediwise-health-suite
```

After installation, OpenClaw will automatically load all skills.

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

**Option C: Configure via setup.py (saved to config.json)**

```bash
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts
python3 setup.py set-vision \
  --provider siliconflow \
  --model Qwen/Qwen2.5-VL-72B-Instruct \
  --api-key sk-xxx \
  --base-url https://api.siliconflow.cn/v1
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

On first use, the system will automatically create databases (split into medical and lifestyle by default):

```
~/.openclaw/skills/mediwise-health-suite/data/medical.db
~/.openclaw/skills/mediwise-health-suite/data/lifestyle.db
```

To manually initialize:

```bash
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts
python3 setup.py init
```

If upgrading from the legacy single database (`health.db`), run the migration:

```bash
cd ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts
python3 setup.py migrate-split-db
python3 setup.py migration-status
```

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
mkdir -p ~/.openclaw/skills/mediwise-health-suite/data
chmod 755 ~/.openclaw/skills/mediwise-health-suite/data
```
