# MediWise 测试场景矩阵

这份清单把“要测哪些情况”拆成了可执行场景，分成：基础流程、边界情况、异常情况、隔离与回归。

## 基础流程

- `B01 成员查询`：按 `owner_id` 查看家庭成员
- `B02 健康摘要`：查看慢病成员摘要与最近指标
- `B03 时间线`：查看住院 / 门诊 / 检验 / 影像混合时间线
- `B04 附件链路`：附件上传、关联、列表展示
- `B05 提醒链路`：自动用药提醒、周期提醒、自定义提醒
- `B06 周期预测`：经期与偏头痛周期预测
- `B07 搜索`：按药物、检验、症状关键词检索
- `B08 导出`：统计导出 / FHIR 导出
- `B09 监测`：阈值、趋势、告警、历史

## 边界情况

- `E01 空成员`：成员存在，但没有任何病历和指标
- `E02 独立记录`：检验 / 影像不挂 visit，也能被 timeline / search 命中
- `E03 历史 + 当前混合`：一年多前旧记录与最近急诊同时存在
- `E04 多条同类指标`：近 7 天连续异常，趋势应该明显
- `E05 紧急值`：血氧 83、体温 39.8、心率 154、血压 186/118
- `E06 到期提醒`：`reminder.py due` 可直接查到需要触发的提醒
- `E07 已完成提醒`：`list --all` 能看到 inactive 历史提醒
- `E08 周期记录不足`：只有 1 条周期起始记录，预测会退回默认周期长度并降低置信度
- `E09 owner 隔离`：`owner_demo_a` 和 `owner_demo_b` 互不串数据

## 异常输入

- `I01 quick_entry 正常混合输入`：中英混合 + 多指标
- `I02 quick_entry 无法解析输入`：应 fallback，而不是错误写库
- `I03 smart_intake 多类型文本`：一段文本里同时包含 visit / medication / metric
- `I04 图片/PDF 未配置视觉模型`：应该给出配置提示，而不是伪造识别结果

## 回归检查

- `R01 check.py 告警后创建提醒`：不应再出现数据库锁问题
- `R02 family-overview`：空成员、历史成员、不同 owner 一起存在时仍能稳定展示
- `R03 summary`：有数据成员和空成员都能返回结构化结果
- `R04 search`：关键词应命中 visits / labs / meds / imaging / observations

## 对应数据集

- 标准数据集：`mediwise-health-tracker/test_data/generated_dataset`
- 边界数据集：`mediwise-health-tracker/test_data/generated_edge_dataset`

## 推荐执行顺序

```bash
python3 mediwise-health-tracker/test_data/generate_sample.py
python3 mediwise-health-tracker/test_data/generate_edge_sample.py
export MEDIWISE_DATA_DIR=$(pwd)/mediwise-health-tracker/test_data/generated_edge_dataset
```

## 重点验证命令

```bash
python3 mediwise-health-tracker/scripts/member.py list --owner-id owner_demo_a
python3 mediwise-health-tracker/scripts/member.py list --owner-id owner_demo_b
python3 mediwise-health-tracker/scripts/query.py summary --member-id mem_empty_sun_qi
python3 mediwise-health-tracker/scripts/query.py timeline --member-id mem_edge_guo_tao
python3 mediwise-health-tracker/scripts/query.py search --keyword 低氧
python3 mediwise-health-tracker/scripts/reminder.py due
python3 mediwise-health-tracker/scripts/reminder.py list --member-id mem_edge_guo_tao --all
python3 mediwise-health-tracker/scripts/cycle_tracker.py predict --member-id mem_edge_guo_tao --cycle-type migraine
python3 health-monitor/scripts/check.py run --member-id mem_edge_guo_tao --window 24h
python3 health-monitor/scripts/alert.py list --member-id mem_edge_guo_tao
python3 health-monitor/scripts/trend.py report --member-id mem_edge_guo_tao
python3 mediwise-health-tracker/scripts/quick_entry.py parse --text "BP 186/118 HR 154 SpO2 83 体温39.8 空腹血糖12.6 体重92kg" --member-id mem_edge_guo_tao
```
