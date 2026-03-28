/**
 * Weight Manager - OpenClaw Skill
 *
 * ESM entry point that routes actions to Python scripts.
 */

import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const execFileAsync = promisify(execFile);
const __dirname = dirname(fileURLToPath(import.meta.url));
const SCRIPTS_DIR = resolve(__dirname, 'scripts');
const HEALTH_SCRIPTS_DIR = resolve(__dirname, '..', 'mediwise-health-tracker', 'scripts');

/**
 * Action-to-script routing table.
 */
const ROUTES = {
  'set-goal': (inputs) => {
    const args = ['set', '--member-id', inputs.member_id,
                  '--goal-type', inputs.params?.goal_type ?? 'lose',
                  '--start-weight', String(inputs.params?.start_weight ?? ''),
                  '--target-weight', String(inputs.params?.target_weight ?? '')];
    const p = inputs.params ?? {};
    if (p.start_date) args.push('--start-date', p.start_date);
    if (p.target_date) args.push('--target-date', p.target_date);
    if (p.daily_calorie_target != null) args.push('--daily-calorie-target', String(p.daily_calorie_target));
    if (p.activity_level) args.push('--activity-level', p.activity_level);
    if (p.note) args.push('--note', p.note);
    return { script: 'weight_goal.py', args };
  },
  'view-goal': (inputs) => ({
    script: 'weight_goal.py',
    args: ['view', '--member-id', inputs.member_id],
  }),
  'update-goal': (inputs) => {
    const args = ['update', '--goal-id', inputs.params?.goal_id ?? ''];
    const p = inputs.params ?? {};
    if (p.target_weight != null) args.push('--target-weight', String(p.target_weight));
    if (p.target_date) args.push('--target-date', p.target_date);
    if (p.daily_calorie_target != null) args.push('--daily-calorie-target', String(p.daily_calorie_target));
    if (p.note) args.push('--note', p.note);
    return { script: 'weight_goal.py', args };
  },
  'complete-goal': (inputs) => ({
    script: 'weight_goal.py',
    args: ['complete', '--goal-id', inputs.params?.goal_id ?? ''],
  }),
  'abandon-goal': (inputs) => ({
    script: 'weight_goal.py',
    args: ['abandon', '--goal-id', inputs.params?.goal_id ?? ''],
  }),
  'weight-progress': (inputs) => ({
    script: 'weight_analysis.py',
    args: ['progress', '--member-id', inputs.member_id],
  }),
  'weight-trend': (inputs) => {
    const args = ['trend', '--member-id', inputs.member_id];
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    return { script: 'weight_analysis.py', args };
  },
  'calorie-balance': (inputs) => {
    const args = ['calorie-balance', '--member-id', inputs.member_id];
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    return { script: 'weight_analysis.py', args };
  },
  'weekly-report': (inputs) => {
    const args = ['weekly-report', '--member-id', inputs.member_id];
    if (inputs.params?.end_date) args.push('--end-date', inputs.params.end_date);
    return { script: 'weight_analysis.py', args };
  },
  'weight-projection': (inputs) => ({
    script: 'weight_analysis.py',
    args: ['projection', '--member-id', inputs.member_id],
  }),
  'diet-weight-correlation': (inputs) => {
    const args = ['diet-weight-correlation', '--member-id', inputs.member_id];
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    return { script: 'weight_analysis.py', args };
  },
  // Exercise routes
  'add-exercise': (inputs) => {
    const args = ['add', '--member-id', inputs.member_id,
                  '--exercise-type', inputs.params?.exercise_type ?? 'other'];
    const p = inputs.params ?? {};
    if (p.exercise_name) args.push('--exercise-name', p.exercise_name);
    if (p.duration != null) args.push('--duration', String(p.duration));
    if (p.calories_burned != null) args.push('--calories-burned', String(p.calories_burned));
    if (p.exercise_date) args.push('--exercise-date', p.exercise_date);
    if (p.exercise_time) args.push('--exercise-time', p.exercise_time);
    if (p.intensity) args.push('--intensity', p.intensity);
    if (p.note) args.push('--note', p.note);
    return { script: 'exercise.py', args };
  },
  'list-exercises': (inputs) => {
    const args = ['list', '--member-id', inputs.member_id];
    const p = inputs.params ?? {};
    if (p.exercise_type) args.push('--exercise-type', p.exercise_type);
    if (p.start_date) args.push('--start-date', p.start_date);
    if (p.end_date) args.push('--end-date', p.end_date);
    if (p.limit != null) args.push('--limit', String(p.limit));
    return { script: 'exercise.py', args };
  },
  'delete-exercise': (inputs) => ({
    script: 'exercise.py',
    args: ['delete', '--id', inputs.params?.id ?? ''],
  }),
  'exercise-summary': (inputs) => {
    const args = ['daily-summary', '--member-id', inputs.member_id];
    if (inputs.params?.date) args.push('--date', inputs.params.date);
    return { script: 'exercise.py', args };
  },
  // Body stats routes
  'calculate-bmi': (inputs) => ({
    script: 'body_stats.py',
    args: ['bmi', '--member-id', inputs.member_id],
  }),
  'calculate-bmr-tdee': (inputs) => {
    const args = ['bmr-tdee', '--member-id', inputs.member_id];
    if (inputs.params?.activity_level) args.push('--activity-level', inputs.params.activity_level);
    return { script: 'body_stats.py', args };
  },
  'suggest-calories': (inputs) => {
    const args = ['suggest-calories', '--member-id', inputs.member_id];
    const p = inputs.params ?? {};
    if (p.activity_level) args.push('--activity-level', p.activity_level);
    if (p.goal_type) args.push('--goal-type', p.goal_type);
    return { script: 'body_stats.py', args };
  },
  'add-measurement': (inputs) => {
    const args = ['add-measurement', '--member-id', inputs.member_id,
                  '--type', inputs.params?.type ?? '',
                  '--value', String(inputs.params?.value ?? '')];
    const p = inputs.params ?? {};
    if (p.measured_at) args.push('--measured-at', p.measured_at);
    if (p.note) args.push('--note', p.note);
    return { script: 'body_stats.py', args };
  },
  'list-measurements': (inputs) => {
    const args = ['list-measurements', '--member-id', inputs.member_id];
    const p = inputs.params ?? {};
    if (p.type) args.push('--type', p.type);
    if (p.limit != null) args.push('--limit', String(p.limit));
    return { script: 'body_stats.py', args };
  },
  'body-summary': (inputs) => ({
    script: 'body_stats.py',
    args: ['body-summary', '--member-id', inputs.member_id],
  }),
};

/**
 * Run a Python script and return parsed JSON output.
 */
async function runScript(script, args) {
  const scriptPath = resolve(SCRIPTS_DIR, script);
  const { stdout } = await execFileAsync('python3', [scriptPath, ...args], {
    timeout: 30_000,
    env: { ...process.env, PYTHONPATH: HEALTH_SCRIPTS_DIR },
  });
  return JSON.parse(stdout.trim());
}

/**
 * OpenClaw Skill entry point.
 */
export async function execute(inputs, context) {
  const { action } = inputs;
  const log = context?.log ?? console.log;
  log(`[weight-manager] action=${action}`);

  const routeFn = ROUTES[action];
  if (!routeFn) {
    return { status: 'error', error: `Unknown action: ${action}` };
  }

  try {
    const { script, args } = routeFn(inputs);

    const ownerId = inputs.owner_id;
    if (ownerId) {
      args.push('--owner-id', ownerId);
    } else {
      log('[weight-manager] WARNING: owner_id not provided; operating in single-user mode (all local data accessible)');
    }

    log(`[weight-manager] script=${script} args=${args.join(' ')}`);
    const result = await runScript(script, args);
    return { status: 'ok', result };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    log(`[weight-manager] error: ${message}`);
    return { status: 'error', error: message };
  }
}
