/**
 * MediWise Sleep Tracker - OpenClaw Skill
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

const ROUTES = {
  'sleep-log': (inputs) => {
    const p = inputs.params ?? {};
    const args = ['log', '--member-id', inputs.member_id,
                  '--duration', String(p.duration ?? '')];
    if (p.deep)  args.push('--deep',  String(p.deep));
    if (p.light) args.push('--light', String(p.light));
    if (p.rem)   args.push('--rem',   String(p.rem));
    if (p.awake) args.push('--awake', String(p.awake));
    if (p.date)  args.push('--date',  p.date);
    return { script: 'sleep.py', args };
  },
  'sleep-daily': (inputs) => {
    const args = ['daily', '--member-id', inputs.member_id];
    if (inputs.params?.date) args.push('--date', inputs.params.date);
    return { script: 'sleep.py', args };
  },
  'sleep-weekly': (inputs) => {
    const args = ['weekly', '--member-id', inputs.member_id];
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    return { script: 'sleep.py', args };
  },
  'sleep-list': (inputs) => {
    const args = ['list', '--member-id', inputs.member_id];
    if (inputs.params?.limit) args.push('--limit', String(inputs.params.limit));
    return { script: 'sleep.py', args };
  },
};

export async function execute(inputs, context) {
  const action = inputs.action;
  const log = context?.log ?? console.log;
  log(`[sleep-tracker] action=${action}`);

  const route = ROUTES[action];
  if (!route) {
    return { status: 'error', error: `未知 action: ${action}` };
  }

  const { script, args } = route(inputs);
  const scriptPath = resolve(SCRIPTS_DIR, script);

  if (inputs.owner_id) {
    args.push('--owner-id', inputs.owner_id);
  } else {
    log('[sleep-tracker] WARNING: owner_id not provided; operating in single-user mode (all local data accessible)');
  }

  log(`[sleep-tracker] script=${script} args=${args.join(' ')}`);

  try {
    const { stdout } = await execFileAsync('python3', [scriptPath, ...args], {
      env: { ...process.env },
      timeout: 30000,
    });
    return { status: 'ok', result: JSON.parse(stdout.trim()) };
  } catch (err) {
    const stdout = err.stdout ?? '';
    try {
      return { status: 'ok', result: JSON.parse(stdout.trim()) };
    } catch {
      const message = (err.stderr ?? '') || err.message;
      log(`[sleep-tracker] error: ${message}`);
      return { status: 'error', error: message };
    }
  }
}
