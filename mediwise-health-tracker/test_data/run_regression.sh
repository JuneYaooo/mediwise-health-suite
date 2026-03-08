#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR="$ROOT_DIR/mediwise-health-tracker/test_data"
LOG_ROOT="$TEST_DIR/regression_logs"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOG_DIR="$LOG_ROOT/$RUN_ID"
mkdir -p "$LOG_DIR"

MODE="all"
KEEP_LOGS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --standard-only)
      MODE="standard"
      ;;
    --edge-only)
      MODE="edge"
      ;;
    --keep-logs)
      KEEP_LOGS=1
      ;;
    -h|--help)
      cat <<'EOF'
Usage:
  bash mediwise-health-tracker/test_data/run_regression.sh [--standard-only|--edge-only] [--keep-logs]

Options:
  --standard-only   只跑标准数据集回归
  --edge-only       只跑边界数据集回归
  --keep-logs       保留详细日志目录
EOF
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
  shift
done

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not found" >&2
  exit 2
fi

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "PASS $1"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  echo "WARN $1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "FAIL $1"
}

run_json() {
  local name="$1"
  shift
  local stdout_file="$LOG_DIR/${name}.stdout.json"
  local stderr_file="$LOG_DIR/${name}.stderr.log"

  if "$@" >"$stdout_file" 2>"$stderr_file"; then
    if jq empty "$stdout_file" >/dev/null 2>&1; then
      return 0
    fi
    echo "Invalid JSON output for $name" >&2
    return 1
  fi
  return 1
}

assert_jq() {
  local name="$1"
  local expr="$2"
  local stdout_file="$LOG_DIR/${name}.stdout.json"
  if jq -e "$expr" "$stdout_file" >/dev/null 2>&1; then
    pass "$name"
  else
    fail "$name"
    echo "  jq assertion failed: $expr" >&2
    echo "  output: $stdout_file" >&2
  fi
}

assert_status_zero_json() {
  local name="$1"
  shift
  if run_json "$name" "$@"; then
    return 0
  fi
  fail "$name"
  echo "  command failed; see $LOG_DIR/${name}.stderr.log" >&2
  return 1
}

standard_suite() {
  echo "== Generating standard dataset =="
  python3 "$TEST_DIR/generate_sample.py" >"$LOG_DIR/standard_manifest.json"
  export MEDIWISE_DATA_DIR="$TEST_DIR/generated_dataset"

  assert_status_zero_json standard_member_list_owner_a \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/member.py" list --owner-id owner_demo_a
  assert_jq standard_member_list_owner_a '.count == 4 and (.members | length == 4)'

  assert_status_zero_json standard_family_overview \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/query.py" family-overview --owner-id owner_demo_a
  assert_jq standard_family_overview '.family_size == 4 and any(.members[]; .id == "mem_self_li_chen")'

  assert_status_zero_json standard_summary_self \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/query.py" summary --member-id mem_self_li_chen
  assert_jq standard_summary_self '.stats.total_visits == 2 and .stats.active_medications == 3 and .latest_metrics.blood_pressure.value.systolic == 168'

  assert_status_zero_json standard_search_hba1c \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/query.py" search --keyword 糖化血红蛋白
  assert_jq standard_search_hba1c '.total_matches >= 1'

  assert_status_zero_json standard_reminder_list_self \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/reminder.py" list --member-id mem_self_li_chen
  assert_jq standard_reminder_list_self '.count >= 4'

  assert_status_zero_json standard_memory_summary \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/memory.py" get-summary --member-id mem_self_li_chen --type all
  assert_jq standard_memory_summary '.status == "ok" and .count == 4 and any(.summaries[]; .summary_type == "profile")'

  assert_status_zero_json standard_cycle_predict \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/cycle_tracker.py" predict --member-id mem_spouse_wang_min --cycle-type menstrual
  assert_jq standard_cycle_predict '.predicted_start != null and .based_on_cycles >= 4'

  assert_status_zero_json standard_attachments \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/attachment.py" list --member-id mem_self_li_chen
  assert_jq standard_attachments '.count >= 2'

  assert_status_zero_json standard_export_statistics \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/export.py" statistics
  assert_jq standard_export_statistics '.member_count >= 5 and .total_visits == 8 and .active_medication_count >= 9'

  assert_status_zero_json standard_export_fhir \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/export.py" fhir --member-id mem_self_li_chen --privacy-level anonymized
  assert_jq standard_export_fhir '.resourceType == "Bundle" and (.entry | length) >= 5'

  assert_status_zero_json standard_quick_entry \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/quick_entry.py" parse --text '今早空腹血糖7.1，血压148/96，心率82，体重77.3kg，血氧97%' --member-id mem_self_li_chen
  assert_jq standard_quick_entry '(.records | length) >= 5'

  assert_status_zero_json standard_thresholds \
    python3 "$ROOT_DIR/health-monitor/scripts/threshold.py" list --member-id mem_self_li_chen
  assert_jq standard_thresholds 'any(.thresholds[]; .metric_type == "heart_rate" and .level == "warning" and .source == "custom")'

  assert_status_zero_json standard_bp_trend \
    python3 "$ROOT_DIR/health-monitor/scripts/trend.py" analyze --member-id mem_self_li_chen --type blood_pressure --days 14
  assert_jq standard_bp_trend '.data_points == 15 and .components.systolic.mean > 150 and .components.diastolic.mean > 90'

  assert_status_zero_json standard_check_first_run \
    python3 "$ROOT_DIR/health-monitor/scripts/check.py" run --member-id mem_self_li_chen --window 24h
  assert_jq standard_check_first_run '.alerts_generated == 4 and any(.alerts[]; .metric_type == "blood_sugar")'

  assert_status_zero_json standard_alert_list \
    python3 "$ROOT_DIR/health-monitor/scripts/alert.py" list --member-id mem_self_li_chen
  assert_jq standard_alert_list '.count >= 4 and any(.alerts[]; .metric_type == "heart_rate")'
}

edge_suite() {
  echo "== Generating edge dataset =="
  python3 "$TEST_DIR/generate_edge_sample.py" >"$LOG_DIR/edge_manifest.json"
  export MEDIWISE_DATA_DIR="$TEST_DIR/generated_edge_dataset"

  assert_status_zero_json edge_owner_a_isolation \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/member.py" list --owner-id owner_demo_a
  assert_jq edge_owner_a_isolation '.count == 6 and any(.members[]; .id == "mem_empty_sun_qi") and any(.members[]; .id == "mem_edge_guo_tao")'

  assert_status_zero_json edge_owner_b_isolation \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/member.py" list --owner-id owner_demo_b
  assert_jq edge_owner_b_isolation '.count == 1 and .members[0].id == "mem_owner_b_zhao_lin"'

  assert_status_zero_json edge_empty_summary \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/query.py" summary --member-id mem_empty_sun_qi
  assert_jq edge_empty_summary '.stats.total_visits == 0 and (.latest_metrics | length == 0)'

  assert_status_zero_json edge_timeline_crisis \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/query.py" timeline --member-id mem_edge_guo_tao
  assert_jq edge_timeline_crisis '.event_count >= 4 and any(.timeline[]; .type == "lab_result") and any(.timeline[]; .type == "imaging")'

  assert_status_zero_json edge_search_hypoxia \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/query.py" search --keyword 低氧
  assert_jq edge_search_hypoxia '.total_matches >= 1'

  assert_status_zero_json edge_due_reminder \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/reminder.py" due
  assert_jq edge_due_reminder '.count == 1 and .due_reminders[0].id == "rem_edge_due_now"'

  assert_status_zero_json edge_all_reminders_before_trigger \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/reminder.py" list --member-id mem_edge_guo_tao --all
  assert_jq edge_all_reminders_before_trigger '.count >= 2 and any(.reminders[]; .id == "rem_edge_inactive_old" and .is_active == 0)'

  assert_status_zero_json edge_cycle_fallback \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/cycle_tracker.py" predict --member-id mem_edge_guo_tao --cycle-type migraine
  assert_jq edge_cycle_fallback '.based_on_cycles == 1 and .confidence == 0.3'

  assert_status_zero_json edge_quick_entry_valid \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/quick_entry.py" parse --text 'BP 186/118 HR 154 SpO2 83 体温39.8 空腹血糖12.6 体重92kg' --member-id mem_edge_guo_tao
  assert_jq edge_quick_entry_valid '(.records | length) >= 6'

  assert_status_zero_json edge_quick_entry_fallback \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/quick_entry.py" parse --text '血压有点高，心率很快，今天不舒服' --member-id mem_edge_guo_tao
  assert_jq edge_quick_entry_fallback '.fallback == true'

  assert_status_zero_json edge_smart_intake_graceful \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/smart_intake.py" extract --text '2026-03-07 夜间突发胸闷和气促，体温39.8℃，血氧83%，心率154次/分。' --member-id mem_edge_guo_tao
  if jq -e '.error != null and (.records | length == 0)' "$LOG_DIR/edge_smart_intake_graceful.stdout.json" >/dev/null 2>&1; then
    pass edge_smart_intake_graceful
    warn edge_smart_intake_graceful_unconfigured
  elif jq -e '(.records | length) >= 1' "$LOG_DIR/edge_smart_intake_graceful.stdout.json" >/dev/null 2>&1; then
    pass edge_smart_intake_graceful
  else
    fail edge_smart_intake_graceful
  fi

  assert_status_zero_json edge_check_emergency \
    python3 "$ROOT_DIR/health-monitor/scripts/check.py" run --member-id mem_edge_guo_tao --window 24h
  assert_jq edge_check_emergency '.alerts_generated == 6 and any(.alerts[]; .level == "emergency")'

  assert_status_zero_json edge_alert_list \
    python3 "$ROOT_DIR/health-monitor/scripts/alert.py" list --member-id mem_edge_guo_tao
  assert_jq edge_alert_list '.count == 6 and any(.alerts[]; .metric_type == "blood_oxygen" and .level == "emergency")'

  assert_status_zero_json edge_trend_report \
    python3 "$ROOT_DIR/health-monitor/scripts/trend.py" report --member-id mem_edge_guo_tao
  assert_jq edge_trend_report '.warning_count >= 3 and (.trends | length) >= 4'

  assert_status_zero_json edge_bp_trend \
    python3 "$ROOT_DIR/health-monitor/scripts/trend.py" analyze --member-id mem_edge_guo_tao --type blood_pressure --days 7
  assert_jq edge_bp_trend '.data_points == 2 and .trend == "declining" and .components.systolic.max == 186'

  assert_status_zero_json edge_reminder_mark_triggered \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/reminder.py" mark-triggered --reminder-id rem_edge_due_now
  assert_jq edge_reminder_mark_triggered '.status == "delivered"'

  assert_status_zero_json edge_all_reminders_after_trigger \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/reminder.py" list --member-id mem_edge_guo_tao --all
  assert_jq edge_all_reminders_after_trigger 'any(.reminders[]; .id == "rem_edge_due_now" and .is_active == 0 and .last_triggered_at != null)'

  local alert_id
  alert_id="$(jq -r '.alerts[0].id' "$LOG_DIR/edge_alert_list.stdout.json")"
  assert_status_zero_json edge_alert_resolve \
    python3 "$ROOT_DIR/health-monitor/scripts/alert.py" resolve --alert-id "$alert_id"
  assert_jq edge_alert_resolve '.status == "ok"'

  assert_status_zero_json edge_alert_list_after_resolve \
    python3 "$ROOT_DIR/health-monitor/scripts/alert.py" list --member-id mem_edge_guo_tao
  assert_jq edge_alert_list_after_resolve '.count == 5'

  assert_status_zero_json edge_attachment_list \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/attachment.py" list --member-id mem_edge_guo_tao
  assert_jq edge_attachment_list '.count >= 1'

  local attachment_id
  attachment_id="$(jq -r '.attachments[0].id' "$LOG_DIR/edge_attachment_list.stdout.json")"
  assert_status_zero_json edge_attachment_get \
    python3 "$ROOT_DIR/mediwise-health-tracker/scripts/attachment.py" get --id "$attachment_id"
  assert_jq edge_attachment_get '.status == "ok" and .attachment.file_exists == true and (.links | length) >= 1'
}

if [[ "$MODE" == "all" || "$MODE" == "standard" ]]; then
  standard_suite
fi
if [[ "$MODE" == "all" || "$MODE" == "edge" ]]; then
  edge_suite
fi

echo
echo "Summary: PASS=$PASS_COUNT WARN=$WARN_COUNT FAIL=$FAIL_COUNT"
echo "Logs: $LOG_DIR"

if [[ $FAIL_COUNT -ne 0 ]]; then
  exit 1
fi

if [[ $KEEP_LOGS -eq 0 ]]; then
  warn logs_kept_for_inspection
fi
