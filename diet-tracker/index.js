/**
 * Diet Tracker - OpenClaw Skill
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
  'add-meal': (inputs) => {
    const args = ['add-meal', '--member-id', inputs.member_id,
                  '--meal-type', inputs.params?.meal_type ?? 'lunch',
                  '--meal-date', inputs.params?.meal_date ?? ''];
    if (inputs.params?.meal_time) args.push('--meal-time', inputs.params.meal_time);
    if (inputs.params?.note) args.push('--note', inputs.params.note);
    if (inputs.params?.items) args.push('--items', JSON.stringify(inputs.params.items));
    return { script: 'diet.py', args };
  },
  'add-item': (inputs) => {
    const args = ['add-item', '--record-id', inputs.params?.record_id ?? ''];
    const p = inputs.params ?? {};
    args.push('--food-name', p.food_name ?? '');
    if (p.amount != null) args.push('--amount', String(p.amount));
    if (p.unit) args.push('--unit', p.unit);
    if (p.calories != null) args.push('--calories', String(p.calories));
    if (p.protein != null) args.push('--protein', String(p.protein));
    if (p.fat != null) args.push('--fat', String(p.fat));
    if (p.carbs != null) args.push('--carbs', String(p.carbs));
    if (p.fiber != null) args.push('--fiber', String(p.fiber));
    if (p.note) args.push('--note', p.note);
    return { script: 'diet.py', args };
  },
  'list-meals': (inputs) => {
    const args = ['list', '--member-id', inputs.member_id];
    const p = inputs.params ?? {};
    if (p.date) args.push('--date', p.date);
    if (p.start_date) args.push('--start-date', p.start_date);
    if (p.end_date) args.push('--end-date', p.end_date);
    if (p.meal_type) args.push('--meal-type', p.meal_type);
    if (p.limit) args.push('--limit', String(p.limit));
    return { script: 'diet.py', args };
  },
  'delete-meal': (inputs) => {
    const args = ['delete', '--id', inputs.params?.id ?? ''];
    if (inputs.params?.type) args.push('--type', inputs.params.type);
    return { script: 'diet.py', args };
  },
  'daily-summary': (inputs) => ({
    script: 'diet.py',
    args: ['daily-summary', '--member-id', inputs.member_id,
           '--date', inputs.params?.date ?? ''],
  }),
  'weekly-summary': (inputs) => {
    const args = ['weekly-summary', '--member-id', inputs.member_id];
    if (inputs.params?.end_date) args.push('--end-date', inputs.params.end_date);
    return { script: 'nutrition.py', args };
  },
  'calorie-trend': (inputs) => {
    const args = ['calorie-trend', '--member-id', inputs.member_id];
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    return { script: 'nutrition.py', args };
  },
  'nutrition-balance': (inputs) => {
    const args = ['nutrition-balance', '--member-id', inputs.member_id];
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    return { script: 'nutrition.py', args };
  },
  'food-lookup': (inputs) => {
    const args = ['search', '--query', inputs.params?.query ?? ''];
    if (inputs.params?.limit) args.push('--limit', String(inputs.params.limit));
    if (inputs.params?.source) args.push('--source', inputs.params.source);
    if (inputs.params?.no_brands) args.push('--no-brands');
    return { script: 'food_lookup.py', args };
  },
  'food-stats': () => ({ script: 'food_lookup.py', args: ['stats'] }),
  // Nutrition goals
  'nutrition-goal-set': (inputs) => {
    const p = inputs.params ?? {};
    const args = ['set', '--member-id', inputs.member_id];
    if (p.calories != null) args.push('--calories', String(p.calories));
    if (p.protein != null)  args.push('--protein',  String(p.protein));
    if (p.fat != null)      args.push('--fat',       String(p.fat));
    if (p.carbs != null)    args.push('--carbs',     String(p.carbs));
    if (p.fiber != null)    args.push('--fiber',     String(p.fiber));
    if (p.note)             args.push('--note',      p.note);
    return { script: 'nutrition_goal.py', args };
  },
  'nutrition-goal-view': (inputs) => ({
    script: 'nutrition_goal.py',
    args: ['view', '--member-id', inputs.member_id],
  }),
  'nutrition-goal-daily': (inputs) => {
    const args = ['daily', '--member-id', inputs.member_id];
    if (inputs.params?.date) args.push('--date', inputs.params.date);
    return { script: 'nutrition_goal.py', args };
  },
  'nutrition-goal-weekly': (inputs) => {
    const args = ['weekly', '--member-id', inputs.member_id];
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    return { script: 'nutrition_goal.py', args };
  },
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
  log(`[diet-tracker] action=${action}`);

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
      log('[diet-tracker] WARNING: owner_id not provided; operating in single-user mode (all local data accessible)');
    }

    log(`[diet-tracker] script=${script} args=${args.join(' ')}`);
    const result = await runScript(script, args);
    return { status: 'ok', result };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    log(`[diet-tracker] error: ${message}`);
    return { status: 'error', error: message };
  }
}
