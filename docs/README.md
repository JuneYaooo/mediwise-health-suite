# MediWise 文档中心

这里汇总 MediWise Health Suite 的用户文档、安装说明、Agent 规则和项目结构。MediWise 支持 Hermes、OpenClaw、Claude Code、Codex、WorkBuddy，以及其他能够加载 Skills、访问本地文件并执行脚本的 Agent 工具。普通用户从项目根目录的 [README](../README.md) 或 [快速开始](../QUICKSTART.md) 阅读即可；只有在安装、排障或参与开发时，才需要继续查看更详细的文档。

## 按需求查文档

| 你要做什么 | 阅读文档 | 适合谁 |
|---|---|---|
| 先了解能做什么、看使用效果 | [README](../README.md) | 所有人 |
| 完成第一次安装和记录 | [快速开始](../QUICKSTART.md) | 普通用户 |
| 安装、备份、恢复或排查问题 | [安装与配置指南](INSTALLATION.md) | 普通用户、配置 Agent |
| 导入 Apple Health 或 Gadgetbridge | [可穿戴数据导入指南](WEARABLES.md) | 普通用户 |
| 查看完整功能范围和典型流程 | [健康管理总览](HEALTH-MANAGEMENT-OVERVIEW.md) | 产品使用者、贡献者 |
| 让 AI 自动完成安装与验收 | [安装 Agent 执行指南](INSTALL_AGENT.md) | 具备本机权限的 Agent |
| 配置 OpenClaw 专用运行边界 | [OpenClaw Agent 配置说明](AGENT_SETUP.md) | OpenClaw 集成者、维护者 |
| 参与开发或修改文档 | [贡献指南](../CONTRIBUTING.md) | 贡献者 |
| 查看版本变化 | [变更记录](../CHANGELOG.md) | 所有人 |

## 项目目录

```text
mediwise-health-suite/
├── README.md                  # 中文产品入口：效果、场景和最短上手路径
├── README_EN.md               # English product overview
├── QUICKSTART.md              # 第一次安装与使用
├── SKILL.md                   # 套件总入口与跨模块规则
├── docs/                      # 用户、安装、集成与架构文档
│   ├── README.md              # 本文档中心
│   ├── INSTALLATION.md        # 面向用户的安装与排障说明
│   ├── INSTALL_AGENT.md       # 面向安装 Agent 的执行步骤
│   ├── AGENT_SETUP.md         # OpenClaw 运行边界
│   ├── HEALTH-MANAGEMENT-OVERVIEW.md
│   ├── WEARABLES.md
│   └── images/                # README 和文档使用的示例图
├── mediwise-health-tracker/   # 成员、医疗记录、指标、用药、提醒和卡片
├── diet-tracker/              # 饮食记录与营养数据汇总
├── weight-manager/            # 体重、围度、运动和用户目标记录
├── sleep-tracker/             # 睡眠记录与趋势汇总
├── health-monitor/            # 用户阈值和规则提醒
├── wearable-sync/             # 可穿戴导出文件导入
├── shared/                    # 各模块共用的 Python 工具
├── install-check.sh           # 安装路径与基础环境检查
├── requirements.txt           # Python 依赖
└── CHANGELOG.md               # 版本变更记录
```

## 六个领域 Skill

| 模块 | 职责 | 模块文档 |
|---|---|---|
| `mediwise-health-tracker` | 家庭成员、健康档案、指标、用药、提醒、附件和健康记录卡片 | [SKILL.md](../mediwise-health-tracker/SKILL.md) |
| `diet-tracker` | 饮食记录、食物数据来源和营养汇总 | [SKILL.md](../diet-tracker/SKILL.md) |
| `weight-manager` | 体重、围度、运动记录和用户目标 | [SKILL.md](../weight-manager/SKILL.md) |
| `sleep-tracker` | 睡眠时长、分期和趋势 | [SKILL.md](../sleep-tracker/SKILL.md) |
| `health-monitor` | 配置阈值、趋势检查和提醒优先级 | [SKILL.md](../health-monitor/SKILL.md) |
| `wearable-sync` | Apple Health、Gadgetbridge 和实验性设备来源 | [SKILL.md](../wearable-sync/SKILL.md) |

每个领域目录遵循相同约定：

- `SKILL.md`：告诉 Agent 何时使用、如何调用以及有哪些边界。
- `index.js`：为 OpenClaw 等支持 action 路由的环境提供脚本适配入口；其他 Agent 可按自身的 Skills 调用机制执行对应脚本。
- `scripts/`：本地数据处理和命令实现。
- `agents/`：特定 Agent 平台需要的元数据；并非每个模块都必须存在。
- `references/`：仅在核心健康档案模块中使用的细分工作流说明。

## 项目架构与数据边界

![从生活片段到本地健康记录：MediWise 使用流程与产品边界](images/architecture.svg)

健康档案和生活方式数据默认保存在本机。当前 Agent 可以直接读取附件时，MediWise 不重复配置视觉服务；OCR、云端视觉、在线食物查询、远程向量搜索和后端 API 都是显式启用的可选能力。更完整的隐私说明见 [安装与配置指南](INSTALLATION.md)。

## 文档维护约定

为了避免同一规则在多个文件中越写越不一致，修改时按下面的职责划分：

- 面向普通用户的效果、场景和能力变化，更新根目录 `README.md`。
- 第一次使用步骤，更新 `QUICKSTART.md`。
- 安装、备份、恢复和排障，更新 `docs/INSTALLATION.md`。
- 安装 Agent 的命令和验收标准，更新 `docs/INSTALL_AGENT.md`。
- Agent 的运行规则和动作说明，更新对应模块的 `SKILL.md`。
- 已发布或待发布的变化，更新 `CHANGELOG.md`。

README 保持面向用户，不展开内部算法、数据库字段或 Provider 配置；实现细节留在 Agent 文档、模块 Skill 和代码中。
