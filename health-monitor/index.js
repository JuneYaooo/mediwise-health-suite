/**
 * MediWise Health Monitor - OpenClaw Skill
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

/**
 * Action-to-script routing table.
 */
const ROUTES = {
  // Dashboard
  'dashboard': (inputs) => ({
    script: 'dashboard.py',
    args: ['show'],
  }),

  // Anomaly detection
  'check-member': (inputs) => ({
    script: 'check.py',
    args: ['run', '--member-id', inputs.member_id, '--window', inputs.params?.window ?? '1h'],
  }),
  'check-all': (inputs) => ({
    script: 'check.py',
    args: ['run-all', '--window', inputs.params?.window ?? '1h'],
  }),

  // Trend analysis
  'trend-analyze': (inputs) => ({
    script: 'trend.py',
    args: ['analyze', '--member-id', inputs.member_id, '--type', inputs.params?.type ?? 'heart_rate', '--days', String(inputs.params?.days ?? 7)],
  }),
  'trend-report': (inputs) => ({
    script: 'trend.py',
    args: ['report', '--member-id', inputs.member_id],
  }),

  // Alert management
  'alert-list': (inputs) => {
    const args = ['list', '--member-id', inputs.member_id];
    if (inputs.params?.level) args.push('--level', inputs.params.level);
    return { script: 'alert.py', args };
  },
  'alert-resolve': (inputs) => {
    const args = ['resolve', '--alert-id', inputs.params?.alert_id ?? ''];
    if (inputs.params?.note) args.push('--note', inputs.params.note);
    return { script: 'alert.py', args };
  },
  'alert-history': (inputs) => ({
    script: 'alert.py',
    args: ['history', '--member-id', inputs.member_id, '--limit', String(inputs.params?.limit ?? 20)],
  }),

  // Threshold management
  'threshold-list': (inputs) => ({
    script: 'threshold.py',
    args: ['list', '--member-id', inputs.member_id],
  }),
  'threshold-set': (inputs) => ({
    script: 'threshold.py',
    args: [
      'set',
      '--member-id', inputs.member_id,
      '--type', inputs.params?.type ?? '',
      '--level', inputs.params?.level ?? '',
      '--direction', inputs.params?.direction ?? '',
      '--value', String(inputs.params?.value ?? ''),
    ],
  }),
  'threshold-reset': (inputs) => ({
    script: 'threshold.py',
    args: ['reset', '--member-id', inputs.member_id, '--type', inputs.params?.type ?? ''],
  }),
};

export async function execute(inputs, context) {
  const action = inputs.action;
  const log = context?.log ?? console.log;
  log(`[health-monitor] action=${action}`);

  const route = ROUTES[action];
  if (!route) {
    return { status: 'error', error: `未知 action: ${action}` };
  }

  const { script, args } = route(inputs);
  const scriptPath = resolve(SCRIPTS_DIR, script);

  if (inputs.owner_id) {
    args.push('--owner-id', inputs.owner_id);
  } else {
    log('[health-monitor] WARNING: owner_id not provided; operating in single-user mode (all local data accessible)');
  }

  log(`[health-monitor] script=${script} args=${args.join(' ')}`);

  try {
    const { stdout } = await execFileAsync('python3', [scriptPath, ...args], {
      env: { ...process.env },
      timeout: 30000,
    });
    return { status: 'ok', result: JSON.parse(stdout.trim()) };
  } catch (err) {
    const stderr = err.stderr ?? '';
    const stdout = err.stdout ?? '';
    try {
      return { status: 'ok', result: JSON.parse(stdout.trim()) };
    } catch {
      const message = stderr || err.message;
      log(`[health-monitor] error: ${message}`);
      return { status: 'error', error: message };
    }
  }
}
