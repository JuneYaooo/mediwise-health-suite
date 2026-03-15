/**
 * MediWise Health Tracker - OpenClaw Skill
 *
 * ESM entry point that routes actions to shared Python scripts.
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
 * Each entry maps an action name to { script, args(inputs) }.
 */
const ROUTES = {
  'list-members': (inputs) => ({
    script: 'member.py',
    args: ['list'],
  }),
  'get-summary': (inputs) => ({
    script: 'query.py',
    args: ['summary', '--member-id', inputs.member_id],
  }),
  'get-timeline': (inputs) => ({
    script: 'query.py',
    args: ['timeline', '--member-id', inputs.member_id],
  }),
  'active-medications': (inputs) => ({
    script: 'query.py',
    args: ['active-medications', '--member-id', inputs.member_id],
  }),
  'get-metrics': (inputs) => {
    const args = ['list', '--member-id', inputs.member_id];
    if (inputs.params?.type) {
      args.push('--type', inputs.params.type);
    }
    return { script: 'health_metric.py', args };
  },
  'get-visits': (inputs) => ({
    script: 'query.py',
    args: ['visits', '--member-id', inputs.member_id],
  }),
  'search': (inputs) => ({
    script: 'query.py',
    args: ['search', '--keyword', inputs.params?.keyword ?? ''],
  }),
  'family-overview': (inputs) => ({
    script: 'query.py',
    args: ['family-overview'],
  }),
  'export-fhir': (inputs) => ({
    script: 'export.py',
    args: ['fhir', '--member-id', inputs.member_id],
  }),
  'statistics': (inputs) => ({
    script: 'export.py',
    args: ['statistics'],
  }),
  'smart-extract': (inputs) => {
    const args = ['extract'];
    if (inputs.params?.text) {
      args.push('--text', inputs.params.text);
    }
    if (inputs.params?.image_base64) {
      args.push('--image-base64', inputs.params.image_base64);
    }
    if (inputs.params?.pdf_path) {
      args.push('--pdf', inputs.params.pdf_path);
    }
    if (inputs.member_id) {
      args.push('--member-id', inputs.member_id);
    }
    return { script: 'smart_intake.py', args };
  },
  'smart-confirm': (inputs) => ({
    script: 'smart_intake.py',
    args: [
      'confirm',
      '--member-id', inputs.member_id,
      '--intake-data', JSON.stringify(inputs.params?.intake_data ?? inputs.params),
    ],
  }),
  'create-reminder': (inputs) => {
    const args = ['create', '--member-id', inputs.member_id];
    const p = inputs.params ?? {};
    if (p.type) args.push('--type', p.type);
    if (p.title) args.push('--title', p.title);
    if (p.schedule_type) args.push('--schedule-type', p.schedule_type);
    if (p.schedule_value) args.push('--schedule-value', p.schedule_value);
    if (p.priority) args.push('--priority', p.priority);
    if (p.content) args.push('--content', p.content);
    return { script: 'reminder.py', args };
  },
  'list-reminders': (inputs) => ({
    script: 'reminder.py',
    args: ['list', '--member-id', inputs.member_id],
  }),
  'update-reminder': (inputs) => {
    const args = ['update', '--reminder-id', inputs.params?.reminder_id ?? ''];
    const p = inputs.params ?? {};
    if (p.title) args.push('--title', p.title);
    if (p.schedule_value) args.push('--schedule-value', p.schedule_value);
    if (p.is_active !== undefined) args.push('--is-active', String(p.is_active));
    if (p.priority) args.push('--priority', p.priority);
    return { script: 'reminder.py', args };
  },
  'delete-reminder': (inputs) => ({
    script: 'reminder.py',
    args: ['delete', '--reminder-id', inputs.params?.reminder_id ?? ''],
  }),
  'health-advice': (inputs) => {
    const args = ['briefing'];
    if (inputs.member_id) {
      args.push('--member-id', inputs.member_id);
    }
    return { script: 'health_advisor.py', args };
  },
  'health-tips': (inputs) => ({
    script: 'health_advisor.py',
    args: ['tips', '--member-id', inputs.member_id],
  }),
  'generate-report': (inputs) => {
    const args = ['screenshot'];
    if (inputs.member_id) {
      args.push('--member-id', inputs.member_id);
    }
    return { script: 'briefing_report.py', args };
  },
  'doctor-visit-report': (inputs) => {
    const args = ['text', '--member-id', inputs.member_id, '--description', inputs.params?.description ?? ''];
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    return { script: 'doctor_visit_report.py', args };
  },
  'doctor-visit-report-image': (inputs) => {
    const args = ['screenshot', '--member-id', inputs.member_id, '--description', inputs.params?.description ?? ''];
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    if (inputs.params?.width) args.push('--width', String(inputs.params.width));
    return { script: 'doctor_visit_report.py', args };
  },
  'doctor-visit-report-pdf': (inputs) => {
    const args = ['pdf', '--member-id', inputs.member_id, '--description', inputs.params?.description ?? ''];
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    return { script: 'doctor_visit_report.py', args };
  },
  'doctor-visit-report-html': (inputs) => {
    const args = ['generate', '--member-id', inputs.member_id, '--description', inputs.params?.description ?? ''];
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    return { script: 'doctor_visit_report.py', args };
  },
  'doctor-visit-report-data': (inputs) => {
    const args = ['data', '--member-id', inputs.member_id, '--description', inputs.params?.description ?? ''];
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    return { script: 'doctor_visit_report.py', args };
  },
  'drug-search': (inputs) => ({
    script: 'drug_interaction.py',
    args: ['search', '--name', inputs.params?.name ?? ''],
  }),
  'drug-check': (inputs) => ({
    script: 'drug_interaction.py',
    args: ['check', '--member-id', inputs.member_id, '--drug-name', inputs.params?.drug_name ?? ''],
  }),
  'drug-check-pair': (inputs) => ({
    script: 'drug_interaction.py',
    args: ['check-pair', '--drug-a', inputs.params?.drug_a ?? '', '--drug-b', inputs.params?.drug_b ?? ''],
  }),
  'drug-lookup': (inputs) => ({
    script: 'drug_interaction.py',
    args: ['lookup', '--name', inputs.params?.name ?? ''],
  }),
  'fda-search': (inputs) => ({
    script: 'openfda_query.py',
    args: ['search', '--name', inputs.params?.name ?? '', '--field', inputs.params?.field ?? 'generic_name'],
  }),
  'fda-interaction': (inputs) => ({
    script: 'openfda_query.py',
    args: ['interaction', '--name', inputs.params?.name ?? ''],
  }),
  'fda-check-pair': (inputs) => ({
    script: 'openfda_query.py',
    args: ['check-pair', '--drug-a', inputs.params?.drug_a ?? '', '--drug-b', inputs.params?.drug_b ?? ''],
  }),
  'quick-entry': (inputs) => ({
    script: 'quick_entry.py',
    args: ['parse', '--text', inputs.params?.text ?? '', '--member-id', inputs.member_id],
  }),
  'quick-entry-save': (inputs) => ({
    script: 'quick_entry.py',
    args: ['parse-and-save', '--text', inputs.params?.text ?? '', '--member-id', inputs.member_id],
  }),
  'cycle-record': (inputs) => {
    const args = ['record', '--member-id', inputs.member_id,
                  '--cycle-type', inputs.params?.cycle_type ?? 'menstrual',
                  '--event-type', inputs.params?.event_type ?? 'period_start',
                  '--date', inputs.params?.date ?? ''];
    if (inputs.params?.details) args.push('--details', JSON.stringify(inputs.params.details));
    return { script: 'cycle_tracker.py', args };
  },
  'cycle-history': (inputs) => {
    const args = ['history', '--member-id', inputs.member_id,
                  '--cycle-type', inputs.params?.cycle_type ?? 'menstrual'];
    if (inputs.params?.limit) args.push('--limit', String(inputs.params.limit));
    return { script: 'cycle_tracker.py', args };
  },
  'cycle-predict': (inputs) => ({
    script: 'cycle_tracker.py',
    args: ['predict', '--member-id', inputs.member_id,
           '--cycle-type', inputs.params?.cycle_type ?? 'menstrual'],
  }),
  'cycle-status': (inputs) => ({
    script: 'cycle_tracker.py',
    args: ['status', '--member-id', inputs.member_id,
           '--cycle-type', inputs.params?.cycle_type ?? 'menstrual'],
  }),
  'auto-cycle-reminders': (inputs) => ({
    script: 'reminder.py',
    args: ['auto-cycle', '--member-id', inputs.member_id,
           '--cycle-type', inputs.params?.cycle_type ?? 'menstrual'],
  }),
  'add-attachment': (inputs) => {
    const args = ['add', '--member-id', inputs.member_id,
                  '--source-path', inputs.params?.source_path ?? '',
                  '--category', inputs.params?.category ?? 'other'];
    if (inputs.params?.description) args.push('--description', inputs.params.description);
    if (inputs.params?.move) args.push('--move');
    if (inputs.params?.link_record_type) args.push('--link-record-type', inputs.params.link_record_type);
    if (inputs.params?.link_record_id) args.push('--link-record-id', inputs.params.link_record_id);
    return { script: 'attachment.py', args };
  },
  'list-attachments': (inputs) => {
    const args = ['list', '--member-id', inputs.member_id];
    if (inputs.params?.category) args.push('--category', inputs.params.category);
    if (inputs.params?.record_type) args.push('--record-type', inputs.params.record_type);
    if (inputs.params?.record_id) args.push('--record-id', inputs.params.record_id);
    if (inputs.params?.limit) args.push('--limit', String(inputs.params.limit));
    return { script: 'attachment.py', args };
  },
  'get-attachment': (inputs) => {
    const args = ['get', '--id', inputs.params?.id ?? ''];
    if (inputs.params?.base64) args.push('--base64');
    return { script: 'attachment.py', args };
  },
  'delete-attachment': (inputs) => {
    const args = ['delete', '--id', inputs.params?.id ?? ''];
    if (inputs.params?.purge) args.push('--purge');
    return { script: 'attachment.py', args };
  },
  'link-attachment': (inputs) => ({
    script: 'attachment.py',
    args: ['link', '--attachment-id', inputs.params?.attachment_id ?? '',
           '--record-type', inputs.params?.record_type ?? '',
           '--record-id', inputs.params?.record_id ?? ''],
  }),
  'unlink-attachment': (inputs) => ({
    script: 'attachment.py',
    args: ['unlink', '--attachment-id', inputs.params?.attachment_id ?? '',
           '--record-type', inputs.params?.record_type ?? '',
           '--record-id', inputs.params?.record_id ?? ''],
  }),
  'get-attachment-url': (inputs) => {
    const args = ['get-url', '--id', inputs.params?.id ?? ''];
    if (inputs.params?.expires) args.push('--expires', String(inputs.params.expires));
    if (inputs.params?.host) args.push('--host', inputs.params.host);
    if (inputs.params?.port) args.push('--port', String(inputs.params.port));
    return { script: 'attachment.py', args };
  },

  // Direct write routes for medical records and metrics
  'add-visit': (inputs) => {
    const args = ['add-visit', '--member-id', inputs.member_id,
                  '--visit-type', inputs.params?.visit_type ?? '门诊',
                  '--visit-date', inputs.params?.visit_date ?? ''];
    const p = inputs.params ?? {};
    if (p.end_date) args.push('--end-date', p.end_date);
    if (p.hospital) args.push('--hospital', p.hospital);
    if (p.department) args.push('--department', p.department);
    if (p.chief_complaint) args.push('--chief-complaint', p.chief_complaint);
    if (p.diagnosis) args.push('--diagnosis', p.diagnosis);
    if (p.summary) args.push('--summary', p.summary);
    return { script: 'medical_record.py', args };
  },
  'add-symptom': (inputs) => {
    const args = ['add-symptom', '--member-id', inputs.member_id,
                  '--symptom', inputs.params?.symptom ?? ''];
    const p = inputs.params ?? {};
    if (p.visit_id) args.push('--visit-id', p.visit_id);
    if (p.severity) args.push('--severity', p.severity);
    if (p.onset_date) args.push('--onset-date', p.onset_date);
    if (p.end_date) args.push('--end-date', p.end_date);
    if (p.description) args.push('--description', p.description);
    return { script: 'medical_record.py', args };
  },
  'add-medication': (inputs) => {
    const args = ['add-medication', '--member-id', inputs.member_id,
                  '--name', inputs.params?.name ?? ''];
    const p = inputs.params ?? {};
    if (p.visit_id) args.push('--visit-id', p.visit_id);
    if (p.dosage) args.push('--dosage', p.dosage);
    if (p.frequency) args.push('--frequency', p.frequency);
    if (p.start_date) args.push('--start-date', p.start_date);
    if (p.end_date) args.push('--end-date', p.end_date);
    if (p.purpose) args.push('--purpose', p.purpose);
    return { script: 'medical_record.py', args };
  },
  'add-metric': (inputs) => {
    const args = ['add', '--member-id', inputs.member_id,
                  '--type', inputs.params?.type ?? '',
                  '--value', String(inputs.params?.value ?? '')];
    const p = inputs.params ?? {};
    if (p.measured_at) args.push('--measured-at', p.measured_at);
    if (p.note) args.push('--note', p.note);
    if (p.source) args.push('--source', p.source);
    if (p.context) args.push('--context', p.context);
    if (p.related_visit_id) args.push('--related-visit-id', p.related_visit_id);
    return { script: 'health_metric.py', args };
  },

  // Visit lifecycle management
  'plan-visit': (inputs) => {
    const args = ['plan', '--member-id', inputs.member_id, '--visit-date', inputs.params?.visit_date ?? ''];
    if (inputs.params?.hospital) args.push('--hospital', inputs.params.hospital);
    if (inputs.params?.department) args.push('--department', inputs.params.department);
    if (inputs.params?.chief_complaint) args.push('--chief-complaint', inputs.params.chief_complaint);
    if (inputs.params?.visit_type) args.push('--visit-type', inputs.params.visit_type);
    return { script: 'visit_lifecycle.py', args };
  },
  'visit-prep': (inputs) => {
    const args = ['prep', '--member-id', inputs.member_id];
    if (inputs.params?.visit_id) args.push('--visit-id', inputs.params.visit_id);
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    return { script: 'visit_lifecycle.py', args };
  },
  'record-visit-outcome': (inputs) => {
    const args = ['outcome', '--visit-id', inputs.params?.visit_id ?? '',
                  '--diagnosis', inputs.params?.diagnosis ?? ''];
    if (inputs.params?.summary) args.push('--summary', inputs.params.summary);
    if (inputs.params?.follow_up_date) args.push('--follow-up-date', inputs.params.follow_up_date);
    if (inputs.params?.follow_up_notes) args.push('--follow-up-notes', inputs.params.follow_up_notes);
    if (inputs.params?.medications) args.push('--medications', JSON.stringify(inputs.params.medications));
    if (inputs.params?.lab_orders) args.push('--lab-orders', JSON.stringify(inputs.params.lab_orders));
    return { script: 'visit_lifecycle.py', args };
  },
  'pending-visits': (inputs) => ({
    script: 'visit_lifecycle.py',
    args: ['pending', '--member-id', inputs.member_id],
  }),

  // Health memory tracking
  'log-health-note': (inputs) => {
    const args = ['log', '--member-id', inputs.member_id, '--content', inputs.params?.content ?? ''];
    if (inputs.params?.category) args.push('--category', inputs.params.category);
    if (inputs.params?.follow_up_days) args.push('--follow-up-days', String(inputs.params.follow_up_days));
    return { script: 'health_memory.py', args };
  },
  'check-health-notes': (inputs) => {
    const args = ['list', '--member-id', inputs.member_id];
    if (inputs.params?.include_resolved) args.push('--include-resolved');
    return { script: 'health_memory.py', args };
  },
  'resolve-health-note': (inputs) => {
    const args = ['resolve', '--note-id', inputs.params?.note_id ?? ''];
    if (inputs.params?.resolution_note) args.push('--resolution-note', inputs.params.resolution_note);
    return { script: 'health_memory.py', args };
  },

  // Medication intake check-in
  'log-medication-taken': (inputs) => {
    const args = ['log-taken', '--member-id', inputs.member_id,
                  '--medication-name', inputs.params?.medication_name ?? ''];
    if (inputs.params?.taken_at) args.push('--taken-at', inputs.params.taken_at);
    if (inputs.params?.dose_taken) args.push('--dose-taken', inputs.params.dose_taken);
    if (inputs.params?.note) args.push('--note', inputs.params.note);
    return { script: 'medication_log.py', args };
  },
  'list-medication-logs': (inputs) => {
    const args = ['list', '--member-id', inputs.member_id];
    if (inputs.params?.medication_name) args.push('--medication-name', inputs.params.medication_name);
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    if (inputs.params?.limit) args.push('--limit', String(inputs.params.limit));
    return { script: 'medication_log.py', args };
  },

  // Chronic disease management
  'setup-chronic-profile': (inputs) => {
    const args = ['setup-profile', '--member-id', inputs.member_id,
                  '--disease-type', inputs.params?.disease_type ?? ''];
    if (inputs.params?.targets) args.push('--targets', JSON.stringify(inputs.params.targets));
    if (inputs.params?.diagnosed_date) args.push('--diagnosed-date', inputs.params.diagnosed_date);
    if (inputs.params?.notes) args.push('--notes', inputs.params.notes);
    return { script: 'chronic_disease.py', args };
  },
  'view-chronic-profile': (inputs) => {
    const args = ['view-profile', '--member-id', inputs.member_id,
                  '--disease-type', inputs.params?.disease_type ?? ''];
    return { script: 'chronic_disease.py', args };
  },
  'analyze-diabetes': (inputs) => {
    const args = ['analyze-diabetes', '--member-id', inputs.member_id];
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    return { script: 'chronic_disease.py', args };
  },
  'analyze-hypertension': (inputs) => {
    const args = ['analyze-hypertension', '--member-id', inputs.member_id];
    if (inputs.params?.days) args.push('--days', String(inputs.params.days));
    return { script: 'chronic_disease.py', args };
  },
  'chronic-disease-summary': (inputs) => {
    const args = ['disease-summary', '--member-id', inputs.member_id];
    if (inputs.params?.disease_type) args.push('--disease-type', inputs.params.disease_type);
    return { script: 'chronic_disease.py', args };
  },

  // Checkup report interpretation
  'interpret-checkup': (inputs) => {
    const args = ['interpret', '--member-id', inputs.member_id];
    if (inputs.params?.text) args.push('--text', inputs.params.text);
    if (inputs.params?.pdf) args.push('--pdf', inputs.params.pdf);
    if (inputs.params?.report_date) args.push('--report-date', inputs.params.report_date);
    if (inputs.params?.save) args.push('--save');
    if (inputs.params?.gender) args.push('--gender', inputs.params.gender);
    return { script: 'checkup_report.py', args };
  },
  'compare-checkups': (inputs) => {
    const args = ['compare', '--member-id', inputs.member_id];
    if (inputs.params?.date1) args.push('--date1', inputs.params.date1);
    if (inputs.params?.date2) args.push('--date2', inputs.params.date2);
    return { script: 'checkup_report.py', args };
  },
};

/**
 * Run a Python script and return parsed JSON output.
 * Accepts an optional env object to inject into the subprocess environment.
 */
async function runScript(script, args, env = {}) {
  const scriptPath = resolve(SCRIPTS_DIR, script);
  const { stdout } = await execFileAsync('python3', [scriptPath, ...args], {
    timeout: 30_000,
    env: { ...process.env, PYTHONPATH: SCRIPTS_DIR, ...env },
  });
  return JSON.parse(stdout.trim());
}

/**
 * OpenClaw Skill entry point.
 *
 * @param {object} inputs - { action: string, member_id?: string, params?: object }
 * @param {object} context - OpenClaw context with log(), env, etc.
 * @returns {Promise<{ status: string, result?: object, error?: string }>}
 */
export async function execute(inputs, context) {
  const { action } = inputs;

  const log = context?.log ?? console.log;
  log(`[mediwise-health-tracker] action=${action}`);

  const routeFn = ROUTES[action];
  if (!routeFn) {
    return { status: 'error', error: `Unknown action: ${action}` };
  }

  try {
    const { script, args } = routeFn(inputs);

    // Build subprocess environment: inject MEDIWISE_OWNER_ID for all scripts
    // so isolation is enforced automatically regardless of which script is called.
    const ownerId = inputs.owner_id;
    const subEnv = {};
    if (ownerId) {
      subEnv.MEDIWISE_OWNER_ID = ownerId;
    }

    log(`[mediwise-health-tracker] script=${script} owner=${ownerId ?? 'none'} args=${args.join(' ')}`);

    const result = await runScript(script, args, subEnv);
    return { status: 'ok', result };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    log(`[mediwise-health-tracker] error: ${message}`);
    return { status: 'error', error: message };
  }
}
