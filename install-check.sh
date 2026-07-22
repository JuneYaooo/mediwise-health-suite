#!/usr/bin/env bash
# install-check.sh — MediWise 安装路径检测工具
#
# 用途：检查套件结构和 Python 导入；在 OpenClaw 的 skills 目录中运行时，
#       同时校验安装路径，防止触发 "escapes plugin root" 沙箱保护。
#
# 用法：
#   bash /path/to/mediwise-health-suite/install-check.sh
#   bash /path/to/mediwise-health-suite/install-check.sh --agent-root /custom/path

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_NAME="mediwise-health-suite"
CHECK_FAILED=0
PATH_OK=1
AGENT_ROOT=""
AGENT_ROOT_EXPLICIT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent-root)
      if [[ $# -lt 2 ]]; then
        echo "--agent-root 需要一个目录参数" >&2
        exit 2
      fi
      AGENT_ROOT="$2"; AGENT_ROOT_EXPLICIT=1; shift 2 ;;
    --agent-root=*)
      AGENT_ROOT="${1#*=}"; AGENT_ROOT_EXPLICIT=1; shift ;;
    *)
      echo "未知参数: $1" >&2
      exit 2 ;;
  esac
done

if [[ "$AGENT_ROOT_EXPLICIT" -eq 1 && -z "$AGENT_ROOT" ]]; then
  echo "--agent-root 不能是空目录" >&2
  exit 2
fi

# ── 颜色输出 ────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}[OK]${RESET}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
err()  { echo -e "${RED}[ERR]${RESET}  $*"; }
info() { echo -e "${CYAN}[INFO]${RESET} $*"; }

echo -e "\n${BOLD}MediWise Health Suite — 安装路径检测${RESET}"
echo "────────────────────────────────────────"
info "Skill 目录: $(basename "$SKILL_DIR")"

# ── 1. 检测并校验 OpenClaw 安装路径 ─────────────────────────────
PARENT_DIR="$(dirname "$SKILL_DIR")"
if [[ -z "$AGENT_ROOT" && "$(basename "$PARENT_DIR")" == "skills" ]]; then
  AGENT_ROOT="$(dirname "$PARENT_DIR")"
fi

if [[ -n "$AGENT_ROOT" ]]; then
  if [[ ! -d "$AGENT_ROOT" ]]; then
    err "Agent 根目录不存在: $AGENT_ROOT"
    exit 1
  fi
  AGENT_ROOT="$(cd "$AGENT_ROOT" && pwd)"
  EXPECTED_PATH="$AGENT_ROOT/skills/$SKILL_NAME"
  if [[ "$SKILL_DIR" == "$EXPECTED_PATH" ]]; then
    ok "OpenClaw 安装路径正确: skills/$SKILL_NAME"
  else
    err "OpenClaw 安装路径不正确"
    err "  当前位置: $SKILL_DIR"
    err "  期望位置: $EXPECTED_PATH"
    err "  路径不匹配可能触发 'escapes plugin root' 保护"
    PATH_OK=0
    CHECK_FAILED=1
  fi
elif [[ "$AGENT_ROOT_EXPLICIT" -eq 0 ]]; then
  warn "当前目录不在标准的 <agent-root>/skills/$SKILL_NAME 路径下"
  warn "按通用 Skills 环境执行结构检查；OpenClaw 安装时请放入实际 workspace 的 skills 目录"
fi

# ── 2. 检查套件结构 ─────────────────────────────────────────────
if [[ -f "$SKILL_DIR/SKILL.md" ]]; then
  ok "SKILL.md 存在"
else
  err "SKILL.md 不存在，OpenClaw 将无法识别此 skill"
  CHECK_FAILED=1
fi

REQUIRED_MODULES=(
  mediwise-health-tracker
  diet-tracker
  weight-manager
  sleep-tracker
  health-monitor
  wearable-sync
)
for module in "${REQUIRED_MODULES[@]}"; do
  if [[ ! -f "$SKILL_DIR/$module/SKILL.md" || ! -d "$SKILL_DIR/$module/scripts" ]]; then
    err "模块结构不完整: $module"
    CHECK_FAILED=1
  fi
done
if [[ ! -f "$SKILL_DIR/shared/path_setup.py" ]]; then
  err "共享路径工具缺失: shared/path_setup.py"
  CHECK_FAILED=1
else
  ok "六个领域模块和共享路径工具完整"
fi

# ── 3. 检查 Python 脚本是否可导入 ───────────────────────────────
SCRIPTS_DIR="$SKILL_DIR/mediwise-health-tracker/scripts"
if [[ -d "$SCRIPTS_DIR" ]]; then
  ok "核心脚本目录存在"
  if SCRIPTS_DIR="$SCRIPTS_DIR" python3 - <<'EOF' 2>/dev/null
import os
import sys
sys.path.insert(0, os.environ["SCRIPTS_DIR"])
import health_db
EOF
  then
    ok "Python 脚本可正常导入"
  else
    err "Python 脚本无法导入"
    CHECK_FAILED=1
  fi
else
  err "脚本目录不存在: $SCRIPTS_DIR"
  CHECK_FAILED=1
fi

# ── 4. 如果路径有问题，给出修复建议 ─────────────────────────────
if [[ "$PATH_OK" -eq 0 ]]; then
  CORRECT_PATH="$AGENT_ROOT/skills/$SKILL_NAME"
  echo ""
  warn "═══════════════════════════════════════════"
  warn "  检测到安装路径问题"
  warn "═══════════════════════════════════════════"
  echo ""
  echo "  预期路径: $CORRECT_PATH"
  echo "  当前路径: $SKILL_DIR"
  echo ""
  echo "  请让具备本机权限的安装 Agent 阅读 docs/INSTALL_AGENT.md，"
  echo "  根据当前 OpenClaw workspace 修复路径后重新执行检查。"
  echo "  项目地址: https://github.com/JuneYaooo/mediwise-health-suite"
  echo "  普通用户不需要手动移动目录、创建链接或运行安装命令。"
  echo ""
  exit 1
fi

if [[ "$CHECK_FAILED" -ne 0 ]]; then
  echo ""
  err "检测未通过，请修复上面的错误后重试。"
  exit 1
fi

echo ""
if [[ -n "$AGENT_ROOT" ]]; then
  ok "所有检查通过，OpenClaw 安装路径正确。"
else
  ok "结构与 Python 导入检查通过；未执行 OpenClaw 专用路径校验。"
fi
echo ""
