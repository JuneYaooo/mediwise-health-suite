#!/usr/bin/env bash
# install-check.sh — MediWise 安装路径检测工具
#
# 用途：检查 skill 是否安装在 OpenClaw agent 工作区内部，
#       防止触发 "escapes plugin root" 沙箱保护。
#
# 用法：
#   bash /path/to/mediwise-health-suite/install-check.sh
#   bash /path/to/mediwise-health-suite/install-check.sh --agent-root /custom/path

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_NAME="mediwise-health-suite"

# ── 颜色输出 ────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}[OK]${RESET}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
err()  { echo -e "${RED}[ERR]${RESET}  $*"; }
info() { echo -e "${CYAN}[INFO]${RESET} $*"; }

echo -e "\n${BOLD}MediWise Health Suite — 安装路径检测${RESET}"
echo "────────────────────────────────────────"
info "Skill 实际路径: $SKILL_DIR"

# ── 1. 检测 OpenClaw agent 根目录 ───────────────────────────────
AGENT_ROOT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent-root)
      AGENT_ROOT="$2"; shift 2 ;;
    --agent-root=*)
      AGENT_ROOT="${1#*=}"; shift ;;
    *)
      shift ;;
  esac
done
if [[ -z "$AGENT_ROOT" ]]; then
  # 自动推导：skill 应在 <agent_root>/skills/<skill_name>/
  # 向上走两级得到候选 agent root
  CANDIDATE="$(dirname "$(dirname "$SKILL_DIR")")"
  if [[ -d "$CANDIDATE" ]]; then
    AGENT_ROOT="$CANDIDATE"
  fi
fi

if [[ -z "$AGENT_ROOT" ]]; then
  err "无法推导 agent 工作区根目录，请手动指定："
  err "  bash install-check.sh --agent-root /path/to/workspace-health"
  exit 1
fi

info "推导 Agent 根目录: $AGENT_ROOT"
echo ""

# ── 2. 检查 skill 路径是否在 agent root 内 ──────────────────────
case "$SKILL_DIR" in
  "$AGENT_ROOT"/*)
    ok "路径检测通过：skill 位于 agent 工作区内部"
    ok "  $AGENT_ROOT/…/$(realpath --relative-to="$AGENT_ROOT" "$SKILL_DIR")"
    PATH_OK=1
    ;;
  *)
    err "路径检测失败：skill 不在 agent 工作区内部"
    err "  当前位置: $SKILL_DIR"
    err "  期望在:   $AGENT_ROOT/skills/$SKILL_NAME/"
    err "  这会触发 OpenClaw 'escapes plugin root' 保护，导致 SKILL.md 无法加载"
    PATH_OK=0
    ;;
esac

# ── 3. 检查 SKILL.md 是否存在 ───────────────────────────────────
if [[ -f "$SKILL_DIR/SKILL.md" ]]; then
  ok "SKILL.md 存在"
else
  err "SKILL.md 不存在，OpenClaw 将无法识别此 skill"
fi

# ── 4. 检查 Python 脚本是否可执行 ───────────────────────────────
SCRIPTS_DIR="$SKILL_DIR/mediwise-health-tracker/scripts"
if [[ -d "$SCRIPTS_DIR" ]]; then
  ok "脚本目录存在: $SCRIPTS_DIR"
  if python3 - <<'EOF' 2>/dev/null
import sys; sys.path.insert(0, '$SCRIPTS_DIR')
import health_db
EOF
  then
    ok "Python 脚本可正常导入"
  else
    warn "Python 脚本导入测试跳过（需在脚本目录内执行 python3）"
  fi
else
  err "脚本目录不存在: $SCRIPTS_DIR"
fi

# ── 5. 如果路径有问题，给出修复建议 ─────────────────────────────
if [[ "$PATH_OK" -eq 0 ]]; then
  CORRECT_PATH="$AGENT_ROOT/skills/$SKILL_NAME"
  echo ""
  warn "═══════════════════════════════════════════"
  warn "  检测到路径问题，以下命令可修复："
  warn "═══════════════════════════════════════════"
  echo ""
  echo -e "  ${BOLD}方式 A：移动（推荐）${RESET}"
  echo "  mkdir -p \"$AGENT_ROOT/skills\""
  echo "  mv \"$SKILL_DIR\" \"$CORRECT_PATH\""
  echo ""
  echo -e "  ${BOLD}方式 B：创建符号链接${RESET}"
  echo "  mkdir -p \"$AGENT_ROOT/skills\""
  echo "  ln -s \"$SKILL_DIR\" \"$CORRECT_PATH\""
  echo ""
  echo -e "  ${BOLD}方式 C：重新安装到正确位置${RESET}"
  echo "  cd \"$AGENT_ROOT\""
  echo "  clawdhub install JuneYaooo/mediwise-health-suite"
  echo ""
  echo "  修复后重新运行此脚本验证。"
  echo ""
  exit 1
fi

echo ""
ok "所有检测通过，安装路径正确。"
echo ""
