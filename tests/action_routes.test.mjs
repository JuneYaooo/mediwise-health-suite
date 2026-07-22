import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const dataDir = mkdtempSync(join(tmpdir(), 'mediwise-actions-'));
process.env.MEDIWISE_DATA_DIR = dataDir;
process.env.MEDIWISE_SINGLE_USER = '1';

const health = await import('../mediwise-health-tracker/index.js');
const diet = await import('../diet-tracker/index.js');
const weight = await import('../weight-manager/index.js');
const sleep = await import('../sleep-tracker/index.js');
const monitor = await import('../health-monitor/index.js');
const wearable = await import('../wearable-sync/index.js');
const context = { log: () => {} };

test('action adapters preserve fields, propagate errors, and complete core workflows', async () => {
  const created = await health.execute({
    action: 'add-member',
    params: {
      name: '测试成员', relation: '本人', gender: 'female', birth_date: '1990-01-01',
      blood_type: 'A', allergies: '花生', medical_history: '测试病史', phone: '000',
      emergency_contact: '联系人', emergency_phone: '111', timezone: 'Asia/Shanghai',
      custom_metric_ranges: { heart_rate: { min: 50, max: 100 } },
    },
  }, context);
  assert.equal(created.status, 'ok');
  const member = created.result.member;
  assert.equal(member.blood_type, 'A');
  assert.equal(member.allergies, '花生');
  assert.equal(member.medical_history, '测试病史');
  assert.equal(member.emergency_contact, '联系人');

  const updated = await health.execute({
    action: 'update-member', member_id: member.id,
    params: { blood_type: 'O', phone: '222' },
  }, context);
  assert.equal(updated.status, 'ok');
  assert.equal(updated.result.member.blood_type, 'O');
  assert.equal(updated.result.member.phone, '222');
  const fetchedMember = await health.execute({
    action: 'get-member', member_id: member.id, params: {},
  }, context);
  assert.equal(fetchedMember.status, 'ok');
  assert.equal(fetchedMember.result.member.name, '测试成员');

  for (const [date, value] of [['2026-07-20 08:00', 60], ['2026-07-22 08:00', 62]]) {
    const metric = await health.execute({
      action: 'add-metric', member_id: member.id,
      params: { type: 'weight', value, measured_at: date },
    }, context);
    assert.equal(metric.status, 'ok');
  }
  const metrics = await health.execute({
    action: 'get-metrics', member_id: member.id,
    params: { type: 'weight', start_date: '2026-07-22', end_date: '2026-07-22', limit: 1 },
  }, context);
  assert.equal(metrics.status, 'ok');
  assert.equal(metrics.result.count, 1);
  assert.equal(metrics.result.metrics[0].value, '62');

  const meal = await diet.execute({
    action: 'add-meal', member_id: member.id,
    params: {
      meal_type: 'lunch', meal_date: '2026-07-22',
      items: [{ food_name: '测试食品', amount: 100, unit: 'g', calories: 200,
        protein: 10, fat: 5, carbs: 30, note: '来源:测试标签' }],
    },
  }, context);
  assert.equal(meal.status, 'ok');

  const exercise = await weight.execute({
    action: 'add-exercise', member_id: member.id,
    params: { exercise_type: 'walking', duration: 30, calories_burned: 120 },
  }, context);
  assert.equal(exercise.status, 'ok');

  const sleepLog = await sleep.execute({
    action: 'sleep-log', member_id: member.id, params: { duration: 420, date: '2026-07-21' },
  }, context);
  assert.equal(sleepLog.status, 'ok');

  const lab = await health.execute({
    action: 'add-lab-result', member_id: member.id,
    params: { test_name: '测试化验', test_date: '2026-07-22', items: [{ name: '项目', value: '1' }] },
  }, context);
  assert.equal(lab.status, 'ok');

  const visit = await health.execute({
    action: 'add-visit', member_id: member.id,
    params: { visit_type: '门诊', visit_date: '2026-07-22', hospital: '测试医院' },
  }, context);
  assert.equal(visit.status, 'ok');
  const visitId = visit.result.visit.id;
  const updatedVisit = await health.execute({
    action: 'update-visit', params: { id: visitId, diagnosis: '测试诊断', visit_status: 'completed' },
  }, context);
  assert.equal(updatedVisit.status, 'ok');
  const visits = await health.execute({
    action: 'list-visits', member_id: member.id,
    params: { start_date: '2026-07-22', end_date: '2026-07-22', visit_type: '门诊' },
  }, context);
  assert.equal(visits.status, 'ok');
  assert.equal(visits.result.count, 1);

  assert.equal((await health.execute({
    action: 'add-symptom', member_id: member.id,
    params: { symptom: '测试症状', visit_id: visitId, severity: '轻度' },
  }, context)).status, 'ok');
  const symptoms = await health.execute({
    action: 'list-symptoms', member_id: member.id, params: { visit_id: visitId },
  }, context);
  assert.equal(symptoms.status, 'ok');
  assert.equal(symptoms.result.count, 1);

  const medication = await health.execute({
    action: 'add-medication', member_id: member.id,
    params: { name: '测试药物', dosage: '1片', frequency: '每日一次', visit_id: visitId },
  }, context);
  assert.equal(medication.status, 'ok');
  const medications = await health.execute({
    action: 'list-medications', member_id: member.id, params: { active_only: true },
  }, context);
  assert.equal(medications.status, 'ok');
  assert.equal(medications.result.count, 1);
  assert.equal((await health.execute({
    action: 'stop-medication', params: { medication_id: medication.result.medication.id,
      end_date: '2026-07-22', reason: '测试停药' },
  }, context)).status, 'ok');

  const labs = await health.execute({
    action: 'list-lab-results', member_id: member.id,
    params: { start_date: '2026-07-22', end_date: '2026-07-22' },
  }, context);
  assert.equal(labs.status, 'ok');
  assert.equal(labs.result.count, 1);
  assert.equal((await health.execute({
    action: 'add-imaging', member_id: member.id,
    params: { exam_name: '测试影像', exam_date: '2026-07-22', visit_id: visitId,
      findings: '测试所见', conclusion: '测试结论' },
  }, context)).status, 'ok');
  const imaging = await health.execute({
    action: 'list-imaging', member_id: member.id,
    params: { start_date: '2026-07-22', end_date: '2026-07-22' },
  }, context);
  assert.equal(imaging.status, 'ok');
  assert.equal(imaging.result.count, 1);

  const snapshot = await health.execute({
    action: 'snapshot-save', member_id: member.id, params: {},
  }, context);
  assert.equal(snapshot.status, 'ok');
  const snapshotDate = snapshot.result.snapshot_date;
  assert.equal((await health.execute({
    action: 'snapshot-get', member_id: member.id, params: { date: snapshotDate },
  }, context)).status, 'ok');
  assert.equal((await health.execute({
    action: 'snapshot-history', member_id: member.id, params: { days: 7 },
  }, context)).status, 'ok');
  assert.equal((await health.execute({
    action: 'snapshot-trend', member_id: member.id, params: { days: 30 },
  }, context)).status, 'ok');

  const invalidCases = [
    ['diet', diet, { action: 'add-meal', member_id: 'missing', params: { meal_date: '2026-07-22' } }],
    ['weight', weight, { action: 'view-goal', member_id: 'missing', params: {} }],
    ['sleep', sleep, { action: 'sleep-log', member_id: 'missing', params: { duration: -1 } }],
    ['monitor', monitor, { action: 'check-member', member_id: 'missing', params: {} }],
    ['wearable', wearable, { action: 'device-add', member_id: 'missing', params: { provider: 'apple_health' } }],
  ];
  for (const [name, module, input] of invalidCases) {
    const result = await module.execute(input, context);
    assert.equal(result.status, 'error', `${name} must propagate business errors`);
    assert.equal(result.result.status, 'error', `${name} must preserve the Python result`);
  }

  const exportXml = join(dataDir, 'export.xml');
  writeFileSync(exportXml, `<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="zh_CN">
  <Record type="HKQuantityTypeIdentifierHeartRate" value="72" unit="count/min" startDate="2026-07-22 08:00:00 +0800" endDate="2026-07-22 08:00:00 +0800"/>
  <Record type="HKQuantityTypeIdentifierStepCount" value="120" unit="count" startDate="2026-07-22 09:00:00 +0800" endDate="2026-07-22 09:05:00 +0800"/>
</HealthData>`);
  const device = await wearable.execute({
    action: 'device-add', member_id: member.id,
    params: { provider: 'apple_health', device_name: '测试导出' },
  }, context);
  assert.equal(device.status, 'ok');
  const deviceId = device.result.device_id;
  assert.equal((await wearable.execute({
    action: 'device-auth', params: { device_id: deviceId, export_path: exportXml },
  }, context)).status, 'ok');
  const synced = await wearable.execute({
    action: 'sync-device', params: { device_id: deviceId },
  }, context);
  assert.equal(synced.status, 'ok');
  assert.equal(synced.result.provider, 'apple_health');
  assert.equal(synced.result.member.id, member.id);
  assert.deepEqual(synced.result.metric_types, ['heart_rate', 'steps']);
  assert.equal(synced.result.time_range.earliest, '2026-07-22 08:00:00');
  assert.equal(synced.result.time_range.latest, '2026-07-22 23:59:00');
});
