# MediWise 合成测试数据

这套数据是**完全合成**的，主要用于覆盖 `mediwise-health-tracker`，同时也能顺带测试 `health-monitor` 的阈值、趋势和告警流程。

## 生成

```bash
python3 mediwise-health-tracker/test_data/generate_sample.py
```

默认会生成到：

- `mediwise-health-tracker/test_data/generated_dataset/health.db`
- `mediwise-health-tracker/test_data/generated_dataset/manifest.json`
- `mediwise-health-tracker/test_data/generated_dataset/fixtures/`

## 数据覆盖

- 5 个成员、2 个 `owner_id`
- 就诊 / 症状 / 用药 / 检验 / 影像 / 健康指标
- 提醒、观察、成员摘要、附件、周期记录
- 饮食、运动、体重目标
- 自定义监测阈值 + 历史告警样本

## 一键回归

```bash
bash mediwise-health-tracker/test_data/run_regression.sh
```

可选参数：

```bash
bash mediwise-health-tracker/test_data/run_regression.sh --standard-only
bash mediwise-health-tracker/test_data/run_regression.sh --edge-only
```

脚本会自动重建数据集，并对查询、提醒、周期、附件、导出、监测、`quick_entry`、`smart_intake` 的关键链路做断言。

## 推荐测试命令

先指定数据目录：

```bash
export MEDIWISE_DATA_DIR=$(pwd)/mediwise-health-tracker/test_data/generated_dataset
```

### 健康档案与查询

```bash
python3 mediwise-health-tracker/scripts/member.py list --owner-id owner_demo_a
python3 mediwise-health-tracker/scripts/query.py family-overview --owner-id owner_demo_a
python3 mediwise-health-tracker/scripts/query.py summary --member-id mem_self_li_chen
python3 mediwise-health-tracker/scripts/query.py timeline --member-id mem_mother_chen_xiulan
python3 mediwise-health-tracker/scripts/query.py search --keyword 糖化血红蛋白
```

### 提醒 / 记忆 / 周期

```bash
python3 mediwise-health-tracker/scripts/reminder.py list --member-id mem_self_li_chen
python3 mediwise-health-tracker/scripts/memory.py get-summary --member-id mem_self_li_chen --type all
python3 mediwise-health-tracker/scripts/memory.py get-context --member-id mem_spouse_wang_min --max-tokens 1200
python3 mediwise-health-tracker/scripts/cycle_tracker.py predict --member-id mem_spouse_wang_min --cycle-type menstrual
python3 mediwise-health-tracker/scripts/cycle_tracker.py status --member-id mem_spouse_wang_min --cycle-type migraine
```

### 附件 / 导出

```bash
python3 mediwise-health-tracker/scripts/attachment.py list --member-id mem_self_li_chen
python3 mediwise-health-tracker/scripts/export.py statistics
python3 mediwise-health-tracker/scripts/export.py fhir --member-id mem_self_li_chen --privacy-level anonymized
```

### 快速录入 / 智能录入

```bash
cat mediwise-health-tracker/test_data/generated_dataset/fixtures/intake_inputs/quick_entry_case_01.txt
python3 mediwise-health-tracker/scripts/quick_entry.py parse --text "今早空腹血糖7.1，血压148/96，心率82，体重77.3kg，血氧97%" --member-id mem_self_li_chen

cat mediwise-health-tracker/test_data/generated_dataset/fixtures/intake_inputs/smart_intake_case_01.txt
cat mediwise-health-tracker/test_data/generated_dataset/fixtures/intake_inputs/smart_intake_case_02_lab.txt
```

说明：`smart_intake.py` 需要你本地先配置好 LLM / Vision，夹带的 `intake_inputs/expected_records.json` 给了每个样例期望覆盖的记录类型。

### health-monitor

```bash
python3 health-monitor/scripts/threshold.py list --member-id mem_self_li_chen
python3 health-monitor/scripts/trend.py analyze --member-id mem_self_li_chen --type blood_pressure --days 14
python3 health-monitor/scripts/trend.py report --member-id mem_self_li_chen
python3 health-monitor/scripts/check.py run --member-id mem_self_li_chen --window 24h
python3 health-monitor/scripts/check.py run --member-id mem_child_li_xiaoyu --window 7d
python3 health-monitor/scripts/alert.py list --member-id mem_self_li_chen
python3 health-monitor/scripts/alert.py history --member-id mem_child_li_xiaoyu
```

## 数据特点

- `mem_self_li_chen`：慢病管理样例，适合测摘要、趋势、药物、随访
- `mem_spouse_wang_min`：偏头痛 + 过敏 + 经期样例，适合测周期与观察
- `mem_child_li_xiaoyu`：急性发热样例，适合测儿科急诊与高温/心率告警
- `mem_mother_chen_xiulan`：老年慢病样例，适合测住院史、血氧、影像与复诊提醒
- `mem_owner_b_zhao_lin`：次租户隔离样例，适合测 `owner_id` 过滤
