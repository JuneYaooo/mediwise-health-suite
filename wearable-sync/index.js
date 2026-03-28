/**
 * MediWise Wearable Sync - OpenClaw Skill
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
  // Device management
  'device-add': (inputs) => {
    const args = ['add', '--member-id', inputs.member_id,
                  '--provider', inputs.params?.provider ?? ''];
    if (inputs.params?.device_name) args.push('--device-name', inputs.params.device_name);
    return { script: 'device.py', args };
  },
  'device-list': (inputs) => ({
    script: 'device.py',
    args: ['list', '--member-id', inputs.member_id],
  }),
  'device-remove': (inputs) => ({
    script: 'device.py',
    args: ['remove', '--device-id', inputs.params?.device_id ?? ''],
  }),
  'device-auth': (inputs) => {
    const args = ['auth', '--device-id', inputs.params?.device_id ?? ''];
    if (inputs.params?.export_path) args.push('--export-path', inputs.params.export_path);
    // Garmin Connect credentials
    if (inputs.params?.username) args.push('--username', inputs.params.username);
    if (inputs.params?.password) args.push('--password', inputs.params.password);
    if (inputs.params?.tokenstore) args.push('--tokenstore', inputs.params.tokenstore);
    // OAuth providers
    if (inputs.params?.client_id) args.push('--client-id', inputs.params.client_id);
    if (inputs.params?.client_secret) args.push('--client-secret', inputs.params.client_secret);
    if (inputs.params?.redirect_uri) args.push('--redirect-uri', inputs.params.redirect_uri);
    return { script: 'device.py', args };
  },
  'device-test': (inputs) => ({
    script: 'device.py',
    args: ['test', '--device-id', inputs.params?.device_id ?? ''],
  }),

  // Data sync
  'sync-device': (inputs) => {
    const args = ['run'];
    if (inputs.params?.device_id) args.push('--device-id', inputs.params.device_id);
    else if (inputs.member_id) args.push('--member-id', inputs.member_id);
    return { script: 'sync.py', args };
  },
  'sync-all': (inputs) => ({
    script: 'sync.py',
    args: ['run-all'],
  }),
  'sync-status': (inputs) => ({
    script: 'sync.py',
    args: ['status', '--device-id', inputs.params?.device_id ?? ''],
  }),
  'sync-history': (inputs) => ({
    script: 'sync.py',
    args: ['history',
           '--device-id', inputs.params?.device_id ?? '',
           '--limit', String(inputs.params?.limit ?? 10)],
  }),
};

export async function execute(inputs, context) {
  const action = inputs.action;
  const log = context?.log ?? console.log;
  log(`[wearable-sync] action=${action}`);

  const route = ROUTES[action];
  if (!route) {
    return { status: 'error', error: `未知 action: ${action}` };
  }

  const { script, args } = route(inputs);
  const scriptPath = resolve(SCRIPTS_DIR, script);

  if (inputs.owner_id) {
    args.push('--owner-id', inputs.owner_id);
  } else {
    log('[wearable-sync] WARNING: owner_id not provided; operating in single-user mode (all local data accessible)');
  }

  log(`[wearable-sync] script=${script} args=${args.join(' ')}`);

  try {
    const { stdout } = await execFileAsync('python3', [scriptPath, ...args], {
      env: { ...process.env },
      timeout: 60000,
    });
    return { status: 'ok', result: JSON.parse(stdout.trim()) };
  } catch (err) {
    const stdout = err.stdout ?? '';
    try {
      return { status: 'ok', result: JSON.parse(stdout.trim()) };
    } catch {
      const message = (err.stderr ?? '') || err.message;
      log(`[wearable-sync] error: ${message}`);
      return { status: 'error', error: message };
    }
  }
}
