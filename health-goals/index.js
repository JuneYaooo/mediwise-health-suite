/** MediWise health-goals Skill action adapter. */

import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { actionResult } from '../shared/action_result.mjs';

const execFileAsync = promisify(execFile);
const __dirname = dirname(fileURLToPath(import.meta.url));
const SCRIPTS_DIR = resolve(__dirname, 'scripts');

function add(args, flag, value) {
  if (value !== undefined && value !== null && value !== '') args.push(flag, String(value));
}

function goalId(inputs) {
  return inputs.params?.goal_id ?? inputs.goal_id ?? '';
}

const ROUTES = {
  'create-health-goal': (inputs) => {
    const p = inputs.params ?? {};
    const args = ['create', '--member-id', inputs.member_id ?? '', '--domain', p.domain ?? '',
      '--goal-type', p.goal_type ?? '', '--title', p.title ?? '',
      '--target-value', String(p.target_value ?? '')];
    add(args, '--total-periods', p.total_periods);
    add(args, '--start-date', p.start_date);
    add(args, '--end-date', p.end_date);
    add(args, '--week-start', p.week_start);
    add(args, '--source', p.source);
    if (p.rules !== undefined) args.push('--rules-json', JSON.stringify(p.rules));
    if (p.confirmed === true) args.push('--confirmed');
    return { script: 'goal.py', args };
  },
  'list-health-goals': (inputs) => {
    const args = ['list', '--member-id', inputs.member_id ?? ''];
    if (inputs.params?.include_inactive === true) args.push('--include-inactive');
    return { script: 'goal.py', args };
  },
  'view-health-goal': (inputs) => ({ script: 'goal.py', args: ['view', '--goal-id', goalId(inputs)] }),
  'health-goal-checkin': (inputs) => {
    const p = inputs.params ?? {};
    const args = ['checkin', '--goal-id', goalId(inputs)];
    add(args, '--occurred-at', p.occurred_at);
    add(args, '--value', p.value);
    add(args, '--duration-minutes', p.duration_minutes);
    add(args, '--source', p.source);
    add(args, '--source-record-type', p.source_record_type);
    add(args, '--source-record-id', p.source_record_id);
    add(args, '--note', p.note);
    return { script: 'goal.py', args };
  },
  'health-goal-progress': (inputs) => {
    const args = ['progress', '--goal-id', goalId(inputs)];
    add(args, '--as-of', inputs.params?.as_of);
    return { script: 'goal.py', args };
  },
  'update-health-goal-status': (inputs) => ({
    script: 'goal.py',
    args: ['status', '--goal-id', goalId(inputs), '--status', inputs.params?.status ?? ''],
  }),
  'list-goal-milestones': (inputs) => {
    const args = ['milestones', '--goal-id', goalId(inputs)];
    if (inputs.params?.unclaimed_only === true) args.push('--unclaimed-only');
    return { script: 'goal.py', args };
  },
  'generate-goal-card': (inputs) => {
    const p = inputs.params ?? {};
    const args = ['generate', '--goal-id', goalId(inputs)];
    add(args, '--milestone-id', p.milestone_id);
    add(args, '--style', p.style);
    add(args, '--tone', p.tone);
    add(args, '--density', p.density);
    add(args, '--seed', p.seed);
    add(args, '--format', p.format);
    add(args, '--output-dir', p.output_dir);
    if (p.redraw === true) args.push('--redraw');
    if (p.show_member_name === true) args.push('--show-member-name');
    if (p.show_exact_date === true) args.push('--show-exact-date');
    return { script: 'goal_card.py', args };
  },
  'list-goal-cards': (inputs) => ({ script: 'goal_card.py', args: ['list', '--goal-id', goalId(inputs)] }),
  'goal-card-preferences': (inputs) => ({
    script: 'goal_card.py', args: ['preferences-get', '--member-id', inputs.member_id ?? ''],
  }),
  'update-goal-card-preferences': (inputs) => {
    const p = inputs.params ?? {};
    const args = ['preferences-update', '--member-id', inputs.member_id ?? ''];
    add(args, '--tone', p.tone);
    add(args, '--density', p.density);
    for (const value of p.like_styles ?? []) add(args, '--like-style', value);
    for (const value of p.dislike_styles ?? []) add(args, '--dislike-style', value);
    for (const value of p.neutral_styles ?? []) add(args, '--neutral-style', value);
    return { script: 'goal_card.py', args };
  },
};

export async function execute(inputs, context) {
  const action = inputs.action;
  const log = context?.log ?? console.log;
  log(`[health-goals] action=${action}`);
  const route = ROUTES[action];
  if (!route) return { status: 'error', error: `未知 action: ${action}` };

  const { script, args } = route(inputs);
  if (inputs.owner_id) {
    args.push('--owner-id', inputs.owner_id);
  } else if (process.env.MEDIWISE_SINGLE_USER !== '1') {
    return {
      status: 'error',
      error: '缺少 owner_id。共享调用必须提供 owner_id；仅个人本地使用时可显式设置 MEDIWISE_SINGLE_USER=1。',
    };
  } else {
    log('[health-goals] single-user mode enabled');
  }

  try {
    const { stdout } = await execFileAsync('python3', [resolve(SCRIPTS_DIR, script), ...args], {
      env: { ...process.env }, timeout: 60000,
    });
    return actionResult(JSON.parse(stdout.trim()));
  } catch (err) {
    try {
      return actionResult(JSON.parse((err.stdout ?? '').trim()));
    } catch {
      const message = (typeof err.stderr === 'string' ? err.stderr.trim() : '')
        || `Python 脚本执行失败（exit=${err?.code ?? 'unknown'}）`;
      log(`[health-goals] script=${script} failed`);
      return { status: 'error', error: message };
    }
  }
}
