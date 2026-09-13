import html
import json
import re
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import briefing_report
import metric_utils


class FamilyHealthCardTest(unittest.TestCase):
    def _family_data(self):
        return {
            "member": {"id": "member-1", "name": "张建国", "relation": "父亲"},
            "member_data": {
                "health_tips": [
                    {"severity": "warning", "title": "血压偏高，请按计划复测"},
                ],
                "due_reminders": [
                    {"id": "reminder-due", "type": "medication", "title": "服药提醒：氨氯地平"},
                ],
            },
            "trends": {
                "blood_pressure": [
                    {"systolic": 138, "diastolic": 86, "date": "2026-07-21"},
                ],
                "heart_rate": [
                    {"value": 72, "date": "2026-07-21"},
                ],
            },
            "lifestyle": {"diet_days": 0, "exercise_count": 0},
            "sleep": {"count": 0},
            "care": {
                "visits": [],
                "labs": [],
                "imaging": [],
                "record_counts": {"visits": 0, "labs": 1, "imaging": 0},
                "abnormal_summary": {
                    "item_count": 1,
                    "reports": [{"test_name": "血脂检查", "abnormal_count": 1}],
                },
            },
            "meds": [
                {
                    "id": "med-1",
                    "name": "氨氯地平",
                    "dosage": "5 mg",
                    "frequency": "每日一次",
                },
            ],
            "reminders": [
                {
                    "id": "med-reminder-1",
                    "type": "medication",
                    "schedule_type": "daily",
                    "schedule_value": "08:00",
                    "related_record_id": "med-1",
                },
                {
                    "id": "checkup-reminder-1",
                    "type": "checkup",
                    "title": "复查血脂",
                    "schedule_type": "once",
                    "next_trigger_at": "2026-08-01 09:00:00",
                },
            ],
        }

    def test_family_card_centers_status_medications_and_attention(self):
        data = self._family_data()
        html = briefing_report._family_content([data], "zh-CN", "member-1")

        self.assertIn("张建国（父亲）", html)
        self.assertIn("当前状态", html)
        self.assertIn("当前用药", html)
        self.assertIn("氨氯地平", html)
        self.assertIn("每天 08:00", html)
        self.assertIn("提醒与注意", html)
        self.assertIn("血脂检查", html)
        self.assertIn("血压偏高，请按计划复测", html)
        self.assertIn("3 项需要注意", html)
        self.assertIn("计划提醒：复查血脂", html)

    def test_family_content_has_no_timeline(self):
        html = briefing_report._family_content([self._family_data()], "zh-CN", None)

        self.assertNotIn("家庭近期医疗时间线", html)
        self.assertNotIn("timeline", html)

    def test_family_card_has_clear_empty_states(self):
        data = self._family_data()
        data["member_data"] = {"health_tips": [], "due_reminders": []}
        data["care"]["abnormal_summary"] = {"item_count": 0, "reports": []}
        data["meds"] = []
        data["reminders"] = []

        html = briefing_report._family_content([data], "zh-CN", None)

        self.assertIn("暂无在用药", html)
        self.assertIn("暂无待处理提醒或明确注意事项", html)
        self.assertIn("当前无明确提醒", html)


class TemperaturePrecisionTest(unittest.TestCase):
    def test_temperature_retains_tenths_in_personal_and_family_cards(self):
        for locale in ("zh-CN", "en-US"):
            for temperature in (36.5, 37.8):
                with self.subTest(locale=locale, temperature=temperature):
                    trends = {"temperature": [{"value": temperature, "date": "2026-09-08"}]}
                    personal = briefing_report._metric_trend_section(trends, locale)
                    family = briefing_report._family_latest_metrics(trends, locale)
                    # One record draws no line, so the value is printed with its unit.
                    self.assertIn(f'<span class="trend-value">{temperature} °C</span>', personal)
                    self.assertNotIn(f">{int(temperature)}<", personal)
                    self.assertIn(f'{temperature} <i>°C</i>', family)

    def test_temperature_retains_tenths_in_rendered_timeline(self):
        for locale in ("zh-CN", "en-US"):
            with self.subTest(locale=locale):
                html = briefing_report._personal_timeline(
                    {"temperature": [{"value": 36.5, "date": "2026-09-08"}]},
                    {}, {}, {"visits": [], "labs": [], "imaging": []}, locale,
                )
                self.assertIn("36.5 °C", html)
                self.assertNotIn("36 °C", html)


class PersonalTimelineEventTest(unittest.TestCase):
    """Timeline events show fields the record already holds, never pasted prose."""

    NARRATIVE = ("现病史：患者3天来反复头晕。\n入院查体：神志清楚，双下肢无明显水肿。\n"
                 "处理计划：调整降压、降糖治疗方案。\n住院号2026090801，床号12。")

    def _visit(self, **overrides):
        visit = {
            "id": "visit-1",
            "visit_date": "2026-09-08",
            "visit_type": "住院",
            "hospital": "青竹市第一虚构医院",
            "department": "老年医学科",
            "chief_complaint": "头晕伴口渴3天，加重1天。",
            "diagnosis": "原发性高血压（3级，极高危）；2型糖尿病",
            # Deliberately present: the row carries the narrative, and the
            # renderer must still not print a word of it.
            "summary": self.NARRATIVE,
        }
        visit.update(overrides)
        return visit

    def _lab(self, items, test_name="血清/尿液检验（13项）"):
        return {"test_date": "2026-09-08", "test_name": test_name, "items": items}

    def _timeline(self, trends=None, care=None, lifestyle=None, locale="zh-CN"):
        care = {"visits": [], "labs": [], "imaging": [], **(care or {})}
        return html.unescape(briefing_report._personal_timeline(
            trends or {}, lifestyle or {}, {}, care, locale))

    def test_the_visit_event_shows_the_extracted_fields(self):
        trends = {
            "blood_pressure": [{"systolic": 178, "diastolic": 96, "date": "2026-09-08",
                                "related_visit_id": "visit-1"}],
            "temperature": [{"value": 36.5, "date": "2026-09-08", "related_visit_id": "visit-1"}],
        }
        out = self._timeline(trends, {"visits": [self._visit()]})

        self.assertIn("原发性高血压（3级，极高危）；2型糖尿病", out)
        self.assertIn("住院 · 青竹市第一虚构医院 · 老年医学科", out)
        self.assertIn("主诉：头晕伴口渴3天，加重1天。", out)
        self.assertIn("血压 178/96 mmHg", out)
        self.assertIn("体温 36.5 °C", out)

    def test_the_visit_event_never_prints_the_source_narrative(self):
        out = self._timeline({}, {"visits": [self._visit()]})

        for marker in ("现病史", "入院查体", "处理计划", "住院号2026090801",
                       "神志清楚", "双下肢无明显水肿"):
            self.assertNotIn(marker, out)

    def test_the_visit_event_does_not_repeat_its_own_title(self):
        out = self._timeline({}, {"visits": [self._visit(diagnosis=None, chief_complaint=None)]})

        self.assertEqual(out.count("老年医学科"), 1)

    def test_a_visit_with_nothing_extracted_says_so(self):
        visit = self._visit(visit_type=None, hospital=None, department=None,
                            chief_complaint=None, diagnosis=None)

        out = self._timeline({}, {"visits": [visit]})

        self.assertIn("未填写", out)

    def test_the_english_locale_labels_the_chief_complaint(self):
        out = self._timeline({}, {"visits": [self._visit()]}, locale="en-US")

        self.assertIn("Chief complaint: 头晕伴口渴3天，加重1天。", out)

    def test_the_imaging_event_shows_the_conclusion_only(self):
        imaging = {"exam_date": "2026-09-09", "exam_name": "胸部CT平扫",
                   "conclusion": "双肺慢性支气管改变。",
                   "findings": "1. 双肺支气管壁轻度增厚。2. 双肺下叶可见少量条索状纤维灶。"}

        out = self._timeline({}, {"imaging": [imaging]})

        self.assertIn("双肺慢性支气管改变。", out)
        self.assertNotIn("双肺支气管壁轻度增厚", out)

    def test_an_imaging_record_without_a_conclusion_is_marked_not_recorded(self):
        imaging = {"exam_date": "2026-09-09", "exam_name": "胸部CT平扫",
                   "findings": "1. 双肺支气管壁轻度增厚。"}

        out = self._timeline({}, {"imaging": [imaging]})

        self.assertIn("未填写", out)
        self.assertNotIn("双肺支气管壁轻度增厚", out)

    def test_the_lab_event_lists_every_flagged_item(self):
        out = self._timeline({}, {"labs": [self._lab([
            {"name": "空腹血糖（FPG）", "value": 9.8, "unit": "mmol/L", "flag": "H"},
            {"name": "糖化血红蛋白（HbA1c）", "value": 8.4, "unit": "%", "flag": "H"},
            {"name": "估算肾小球滤过率（eGFR）", "value": 58, "unit": "mL/min/1.73m²", "flag": "L"},
            {"name": "总胆固醇（TC）", "value": 5.7, "unit": "mmol/L", "flag": "H"},
            {"name": "血肌酐（Cr）", "value": 108, "unit": "μmol/L", "flag": ""},
        ])]})

        self.assertIn("4 项明确异常", out)
        for label in ("空腹血糖（FPG） · 9.8 mmol/L · H",
                      "糖化血红蛋白（HbA1c） · 8.4 % · H",
                      "估算肾小球滤过率（eGFR） · 58 mL/min/1.73m² · L",
                      "总胆固醇（TC） · 5.7 mmol/L · H"):
            self.assertIn(label, out)
        self.assertNotIn("血肌酐（Cr）", out)

    def test_a_dash_placeholder_is_not_printed_as_a_unit(self):
        out = self._timeline({}, {"labs": [self._lab([
            {"name": "尿常规：蛋白", "value": "±（微量）", "unit": "-", "flag": "H"}])]})

        self.assertIn("尿常规：蛋白 · ±（微量） · H", out)

    def test_a_lab_without_flags_says_so(self):
        out = self._timeline({}, {"labs": [self._lab([
            {"name": "血肌酐（Cr）", "value": 108, "unit": "μmol/L"}])]})

        self.assertIn("无明确异常标记", out)

    def test_the_default_lab_summary_still_caps_its_labels(self):
        """The family card's one-line summary keeps its two-label cap."""
        lab = self._lab([
            {"name": "空腹血糖（FPG）", "value": 9.8, "unit": "mmol/L", "flag": "H"},
            {"name": "糖化血红蛋白（HbA1c）", "value": 8.4, "unit": "%", "flag": "H"},
            {"name": "总胆固醇（TC）", "value": 5.7, "unit": "mmol/L", "flag": "H"},
            {"name": "尿常规：蛋白", "value": "±（微量）", "unit": "-", "flag": "H"},
        ])

        count, labels = briefing_report._lab_abnormal_details(lab)

        self.assertEqual((count, len(labels)), (4, 2))
        self.assertEqual(len(briefing_report._lab_abnormal_details(lab, limit=None)[1]), 4)

    def test_a_measured_value_is_not_repeated_as_a_metric_update(self):
        trends = {"temperature": [{"value": 36.5, "date": "2026-09-08",
                                   "related_visit_id": "visit-1"}]}

        out = self._timeline(trends, {"visits": [self._visit()]})

        self.assertEqual(out.count("体温 36.5 °C"), 1)
        self.assertNotIn("健康指标更新", out)

    def test_a_newer_unlinked_reading_keeps_its_own_event(self):
        trends = {"temperature": [{"value": 36.5, "date": "2026-09-08", "related_visit_id": "visit-1"},
                                  {"value": 38.2, "date": "2026-09-10"}]}

        out = self._timeline(trends, {"visits": [self._visit()]})

        self.assertIn("健康指标更新", out)
        self.assertIn("体温 38.2 °C", out)
        self.assertIn("体温 36.5 °C", out)

    def test_a_measurement_linked_to_a_visit_off_the_card_stays_visible(self):
        trends = {"temperature": [{"value": 38.2, "date": "2026-09-10",
                                   "related_visit_id": "visit-gone"}]}

        out = self._timeline(trends, {"visits": [self._visit()]})

        self.assertIn("健康指标更新", out)
        self.assertIn("体温 38.2 °C", out)

    def test_a_visit_cut_by_the_event_cap_does_not_take_its_values_away(self):
        exercises = [{"exercise_name": "散步", "duration": 30, "calories_burned": 90,
                      "exercise_date": f"2026-09-{day:02d}"} for day in range(17, 26)]
        trends = {"temperature": [{"value": 36.5, "date": "2026-09-08", "related_visit_id": "visit-1"},
                                  {"value": 38.2, "date": "2026-09-15", "related_visit_id": "visit-1"}]}

        out = self._timeline(trends, {"visits": [self._visit()]},
                             lifestyle={"recent_exercise": exercises})

        # Nine newer activity events fill the cap, so the visit event is cut.
        self.assertNotIn("青竹市第一虚构医院", out)
        self.assertIn("健康指标更新", out)
        self.assertIn("体温 38.2 °C", out)


class ClinicalSnapshotTest(unittest.TestCase):
    """The clinical header must show the whole picture, with sources kept apart."""

    def _member(self):
        return {
            "id": "member-1", "name": "熊猫", "relation": "本人", "gender": "男",
            "birth_date": None, "age_years": 89, "age_recorded_at": "2026-09-08",
            "allergies": "否认食物、药物过敏史",
            "medical_history": "高血压病史约20年，2型糖尿病病史约15年。",
        }

    def _snapshot(self):
        items = [
            {"name": "空腹血糖（FPG）", "value": 9.8, "unit": "mmol/L", "reference": "3.9 - 6.1", "flag": "H", "is_abnormal": True},
            {"name": "糖化血红蛋白（HbA1c）", "value": 8.4, "unit": "%", "reference": "4.0 - 6.0", "flag": "H", "is_abnormal": True},
            {"name": "估算肾小球滤过率（eGFR）", "value": 58, "unit": "mL/min/1.73m²", "reference": "≥ 90", "flag": "L", "is_abnormal": True},
            {"name": "总胆固醇（TC）", "value": 5.7, "unit": "mmol/L", "reference": "< 5.2", "flag": "H", "is_abnormal": True},
            {"name": "低密度脂蛋白胆固醇（LDL-C）", "value": 3.6, "unit": "mmol/L", "reference": "< 3.4", "flag": "H", "is_abnormal": True},
            {"name": "尿常规：蛋白", "value": "±（微量）", "unit": "", "reference": "阴性", "flag": "H", "is_abnormal": True},
        ]
        return {
            "diagnoses": [
                {"diagnosis": "原发性高血压（3级，极高危）", "visit_date": "2026-09-08",
                 "hospital": "青竹市第一虚构医院", "department": "老年医学科"},
                {"diagnosis": "2型糖尿病", "visit_date": "2026-09-08",
                 "hospital": "青竹市第一虚构医院", "department": "老年医学科"},
            ],
            "abnormal_reports": [{"test_date": "2026-09-08", "test_name": "血清/尿液检验（13项）", "items": items}],
        }

    def _member_data(self):
        return {
            "health_tips": [
                {"type": "metric_anomaly", "severity": "alert", "title": "血压高于配置范围",
                 "detail": "收缩压：178.0 mmHg（参考范围 90-150）"},
                {"type": "metric_gap", "severity": "info", "title": "血压已 4 天未测量"},
            ],
            "due_reminders": [],
        }

    def _html(self, snapshot=None, member=None, member_data=None, locale="zh-CN"):
        """Render the block, unescaped so assertions can read it as text."""
        return html.unescape(briefing_report._snapshot_section(
            member if member is not None else self._member(),
            snapshot if snapshot is not None else self._snapshot(),
            member_data if member_data is not None else self._member_data(),
            locale,
        ))

    def test_every_flagged_item_is_listed_with_its_reference_range(self):
        html = self._html()

        for name, value, reference in (
            ("空腹血糖（FPG）", "9.8 mmol/L", "3.9 - 6.1"),
            ("糖化血红蛋白（HbA1c）", "8.4 %", "4.0 - 6.0"),
            ("估算肾小球滤过率（eGFR）", "58 mL/min/1.73m²", "≥ 90"),
            ("总胆固醇（TC）", "5.7 mmol/L", "< 5.2"),
            ("低密度脂蛋白胆固醇（LDL-C）", "3.6 mmol/L", "< 3.4"),
            ("尿常规：蛋白", "±（微量）", "阴性"),
        ):
            with self.subTest(item=name):
                self.assertIn(name, html)
                self.assertIn(value, html)
                self.assertIn(f"参考 {reference}", html)

    def test_items_the_report_did_not_flag_stay_out(self):
        """Only items the report itself marked are drawn — nothing is judged here."""
        html = self._html()

        self.assertNotIn("钾（K⁺）", html)
        self.assertNotIn("钠（Na⁺）", html)
        self.assertNotIn("4.1", html)

    def test_report_flags_and_threshold_alerts_are_rendered_apart(self):
        html = self._html()

        self.assertIn("报告标记的异常", html)
        self.assertIn("阈值告警", html)
        # The report's own marker carries the value it was printed against.
        self.assertIn('class="snapshot-flag high">H<', html)
        self.assertIn('class="snapshot-flag low">L<', html)
        # A configured-range alert shows its measured value, not just a title.
        self.assertIn("收缩压：178.0 mmHg（参考范围 90-150）", html)
        report_block = html.split("阈值告警")[0]
        self.assertNotIn("血压高于配置范围", report_block)

    def test_dash_placeholder_unit_is_not_rendered(self):
        html = self._html()

        self.assertIn("<span>±（微量）</span>", html)
        self.assertNotIn("±（微量） -", html)

    def test_a_precision_the_report_printed_is_not_rounded_away(self):
        html = self._html()

        self.assertIn("<span>9.8 mmol/L</span>", html)

    def test_diagnoses_render_as_separate_chips_with_their_source(self):
        html = self._html()

        self.assertIn('<span class="snapshot-chip">原发性高血压（3级，极高危）</span>', html)
        self.assertIn('<span class="snapshot-chip">2型糖尿病</span>', html)
        self.assertIn("2026-09-08 · 青竹市第一虚构医院 · 老年医学科", html)

    def test_history_and_allergies_are_shown(self):
        html = self._html()

        self.assertIn("既往史", html)
        self.assertIn("高血压病史约20年", html)
        self.assertIn("过敏史", html)
        self.assertIn("否认食物、药物过敏史", html)

    def test_block_is_omitted_when_nothing_clinical_is_recorded(self):
        html = self._html(
            snapshot={"diagnoses": [], "abnormal_reports": []},
            member={"id": "member-2", "name": "空白", "relation": "本人"},
            member_data={"health_tips": [], "due_reminders": []},
        )

        self.assertEqual(html, "")

    def test_english_locale_uses_english_labels(self):
        html = self._html(locale="en-US")

        self.assertIn("Clinical snapshot", html)
        self.assertIn("Flags printed on the report", html)
        self.assertIn("Configured-range alerts", html)
        self.assertIn("Medical history", html)


class ClinicalSnapshotDataTest(unittest.TestCase):
    """The data layer must hand the renderer every flagged item, unabridged."""

    def _lab_row(self, **overrides):
        items = [
            {"name": "空腹血糖（FPG）", "value": 9.8, "unit": "mmol/L", "reference": "3.9 - 6.1", "flag": "H"},
            {"name": "糖化血红蛋白（HbA1c）", "value": 8.4, "unit": "%", "reference": "4.0 - 6.0", "flag": "H"},
            {"name": "估算肾小球滤过率（eGFR）", "value": 58, "unit": "mL/min/1.73m²", "reference": "≥ 90", "flag": "L"},
            {"name": "总胆固醇（TC）", "value": 5.7, "unit": "mmol/L", "reference": "< 5.2", "flag": "H"},
            {"name": "低密度脂蛋白胆固醇（LDL-C）", "value": 3.6, "unit": "mmol/L", "reference": "< 3.4", "flag": "H"},
            {"name": "尿常规：蛋白", "value": "±（微量）", "unit": "-", "reference": "阴性", "flag": "H"},
            {"name": "钾（K⁺）", "value": 4.1, "unit": "mmol/L", "reference": "3.5 - 5.3", "flag": ""},
            {"name": "钠（Na⁺）", "value": 141, "unit": "mmol/L", "reference": "137 - 147", "status": "normal"},
        ]
        row = {"test_date": "2026-09-08", "test_name": "血清/尿液检验", "items": json.dumps(items, ensure_ascii=False)}
        row.update(overrides)
        return row

    def test_every_flagged_item_survives_the_data_layer(self):
        groups = briefing_report._abnormal_report_groups([self._lab_row()])

        self.assertEqual(len(groups), 1)
        self.assertEqual([item["name"] for item in groups[0]["items"]],
                         ["空腹血糖（FPG）", "糖化血红蛋白（HbA1c）", "估算肾小球滤过率（eGFR）",
                          "总胆固醇（TC）", "低密度脂蛋白胆固醇（LDL-C）", "尿常规：蛋白"])

    def test_items_without_a_printed_flag_are_not_promoted_to_abnormal(self):
        names = [item["name"] for item in briefing_report._abnormal_report_groups([self._lab_row()])[0]["items"]]

        self.assertNotIn("钾（K⁺）", names)
        self.assertNotIn("钠（Na⁺）", names)

    def test_a_dash_placeholder_is_read_as_no_unit(self):
        item = briefing_report._abnormal_item({"name": "尿常规：蛋白", "value": "±（微量）", "unit": "-", "reference": "-", "flag": "H"})

        self.assertEqual(item["unit"], "")
        self.assertEqual(item["reference"], "")
        self.assertEqual(item["value"], "±（微量）")
        self.assertEqual(item["flag"], "H")

    def test_the_same_analyte_on_two_reports_is_kept_twice(self):
        groups = briefing_report._abnormal_report_groups([
            self._lab_row(test_date="2026-09-08"),
            self._lab_row(test_date="2026-03-02"),
        ])

        self.assertEqual([group["test_date"] for group in groups], ["2026-09-08", "2026-03-02"])
        self.assertEqual(len(groups[0]["items"]), len(groups[1]["items"]))

    def test_a_report_with_nothing_flagged_produces_no_group(self):
        quiet = json.dumps([{"name": "钾（K⁺）", "value": 4.1, "unit": "mmol/L", "flag": ""}], ensure_ascii=False)

        self.assertEqual(briefing_report._abnormal_report_groups(
            [{"test_date": "2026-09-08", "test_name": "复查", "items": quiet}]), [])

    def test_the_snapshot_count_matches_what_is_drawn(self):
        snapshot = {"abnormal_reports": briefing_report._abnormal_report_groups([self._lab_row()])}

        self.assertEqual(briefing_report._snapshot_abnormal_count(snapshot), 6)


class DiagnosisCollapseTest(unittest.TestCase):
    def test_semicolon_separated_phrases_split_and_commas_stay_inside(self):
        collapsed = briefing_report._collapse_diagnoses([
            {"visit_date": "2026-09-08", "diagnosis": "原发性高血压（3级，极高危）；2型糖尿病；头晕待查（入院记录原文）"},
        ])

        self.assertEqual(
            [item["diagnosis"] for item in collapsed],
            ["原发性高血压（3级，极高危）", "2型糖尿病", "头晕待查（入院记录原文）"],
        )

    def test_a_repeated_diagnosis_keeps_its_most_recent_visit(self):
        collapsed = briefing_report._collapse_diagnoses([
            {"visit_date": "2026-09-08", "diagnosis": "2型糖尿病", "hospital": "最近一次医院"},
            {"visit_date": "2019-03-02", "diagnosis": "2型糖尿病", "hospital": "多年前医院"},
        ])

        self.assertEqual(len(collapsed), 1)
        self.assertEqual(collapsed[0]["visit_date"], "2026-09-08")
        self.assertEqual(collapsed[0]["hospital"], "最近一次医院")

    def test_blank_diagnoses_are_skipped(self):
        self.assertEqual(briefing_report._collapse_diagnoses([{"visit_date": "2026-09-08", "diagnosis": "  ； "}]), [])


class AttentionBlockTest(unittest.TestCase):
    def test_threshold_alerts_are_left_to_the_clinical_snapshot(self):
        member_data = {
            "health_tips": [
                {"type": "metric_anomaly", "severity": "alert", "title": "血压高于配置范围"},
                {"type": "metric_gap", "severity": "info", "title": "血压已 4 天未测量"},
                {"type": "overdue_checkup", "severity": "warning", "title": "距上次复查已超过建议间隔"},
            ],
            "due_reminders": [],
        }

        html = briefing_report._attention_section(member_data, "zh-CN")

        self.assertNotIn("血压高于配置范围", html)
        self.assertIn("血压已 4 天未测量", html)
        self.assertIn("距上次复查已超过建议间隔", html)

    def test_section_is_omitted_when_only_threshold_alerts_remain(self):
        member_data = {
            "health_tips": [{"type": "metric_anomaly", "severity": "alert", "title": "血压高于配置范围"}],
            "due_reminders": [],
        }

        self.assertEqual(briefing_report._attention_section(member_data, "zh-CN"), "")

    def test_a_multi_digit_gap_keeps_every_digit_in_english(self):
        """A -6 slice read "血氧已 10 天未测量" as a one-day gap."""
        member_data = {
            "health_tips": [{"type": "metric_gap", "severity": "info", "title": "血氧已 10 天未测量"}],
            "due_reminders": [],
        }

        html = briefing_report._attention_section(member_data, "en-US")

        self.assertIn("No blood oxygen measurement for 10 days", html)

    def test_a_one_day_gap_is_singular_in_english(self):
        member_data = {
            "health_tips": [{"type": "metric_gap", "severity": "info", "title": "血压已 1 天未测量"}],
            "due_reminders": [],
        }

        html = briefing_report._attention_section(member_data, "en-US")

        self.assertIn("No blood pressure measurement for 1 day", html)
        self.assertNotIn("1 days", html)


class MetricTrendTest(unittest.TestCase):
    def test_single_record_states_the_value_and_no_trend(self):
        html = briefing_report._metric_trend_section(
            {"heart_rate": [{"value": 78, "date": "2026-09-08", "source": "manual"}]}, "zh-CN")

        self.assertIn("心率", html)
        self.assertIn("78", html)
        self.assertIn("1 条", html)
        self.assertIn("2026-09-08", html)
        self.assertIn("来源: 手动记录", html)
        self.assertNotIn("<svg", html)
        self.assertNotIn("<circle", html)

    def test_two_records_draw_a_chart_with_both_values_and_dates(self):
        html = briefing_report._metric_trend_section(
            {"heart_rate": [{"value": 70, "date": "2026-09-01", "source": "manual"},
                            {"value": 78, "date": "2026-09-08", "source": "manual"}]}, "zh-CN")

        self.assertIn('<svg class="chart"', html)
        self.assertIn('<polyline', html)
        for text in ("70", "78", "09-01", "09-08"):
            self.assertIn(f">{text}</text>", html)

    def test_a_lone_record_never_reads_as_a_missing_trend_verdict(self):
        """The count badge already says how many records there are."""
        html = briefing_report._metric_trend_section(
            {"heart_rate": [{"value": 78, "date": "2026-09-08", "source": "manual"}]}, "zh-CN")

        self.assertNotIn("记录不足，暂不判断趋势", html)
        self.assertNotIn("较期初", html)

    def test_ordering_puts_named_types_first_then_the_richest_series(self):
        html = briefing_report._metric_trend_section(
            {"heart_rate": [{"value": 70, "date": "2026-09-01", "source": "manual"},
                            {"value": 78, "date": "2026-09-02", "source": "manual"},
                            {"value": 80, "date": "2026-09-03", "source": "manual"}],
             "weight": [{"value": 70.0, "date": "2026-09-01", "source": "manual"},
                        {"value": 71.0, "date": "2026-09-02", "source": "manual"}]}, "zh-CN",
            ["weight"])

        self.assertLess(html.index("体重"), html.index("心率"))

    def test_empty_series_keeps_the_existing_empty_state(self):
        self.assertIn("暂无可展示的健康指标",
                      briefing_report._metric_trend_section({}, "zh-CN"))


class MetricTrendChartTest(unittest.TestCase):
    """The chart is a scale for recorded numbers and nothing else."""

    # Colours the SVG may use: the series palette, the point outline, the
    # gridlines, the baseline, and the two text greys. Any other colour would
    # be a value-dependent judgement drawn on the picture.
    PALETTE = set(briefing_report.SERIES_COLORS) | {"#FFFFFF", "#E3EDF7", "#C9DBEB", "#587087", "#15324B"}

    @staticmethod
    def _points(values, metric_type="heart_rate", start=1, source="manual"):
        return [{"value": value, "date": f"2026-09-{start + index:02d}", "source": source,
                 "metric_type": metric_type} for index, value in enumerate(values)]

    @staticmethod
    def _xs(svg):
        return [float(match) for match in re.findall(r'<circle cx="([\d.]+)"', svg)]

    def test_blood_pressure_draws_two_labelled_series(self):
        html = briefing_report._metric_trend_section(
            {"blood_pressure": [{"date": "2026-09-01", "source": "manual", "systolic": 148, "diastolic": 92},
                                {"date": "2026-09-08", "source": "manual", "systolic": 133, "diastolic": 80}]},
            "zh-CN")

        self.assertEqual(html.count("<polyline"), 2)
        self.assertIn(briefing_report.SERIES_COLORS[0], html)
        self.assertIn(briefing_report.SERIES_COLORS[1], html)
        self.assertIn("收缩压", html)
        self.assertIn("舒张压", html)

    def test_a_measured_context_is_charted_even_when_it_is_not_the_first_key(self):
        """A 餐后 record carries `postprandial` and no `value` at all."""
        html = briefing_report._metric_trend_section(
            {"blood_sugar": [{"date": "2026-09-01", "source": "manual", "metric_type": "blood_sugar",
                              "fasting": 5.8},
                             {"date": "2026-09-03", "source": "manual", "metric_type": "blood_sugar",
                              "postprandial": 7.4},
                             {"date": "2026-09-08", "source": "manual", "metric_type": "blood_sugar",
                              "fasting": 6.1, "postprandial": 8.2}]},
            "zh-CN")

        self.assertEqual(html.count("<polyline"), 2)
        self.assertIn("空腹", html)
        self.assertIn("餐后", html)
        for value in ("5.8", "7.4", "8.2"):
            self.assertIn(value, html)

    def test_a_long_wearable_series_is_sampled_and_the_rest_is_counted(self):
        """A 90-day heart-rate export is thousands of samples, not a chart."""
        dates = [f"2026-{month:02d}-{day:02d}" for month in (6, 7, 8) for day in range(1, 31)]
        points = [{"date": date, "source": "apple_health", "metric_type": "heart_rate",
                   "value": 60 + index % 25} for index, date in enumerate(dates * 10)]

        html = briefing_report._metric_trend_section({"heart_rate": points}, "zh-CN")
        drawn = len(re.findall(r'<polyline points="([^"]+)"', html)[0].split())

        self.assertLessEqual(drawn, briefing_report.MAX_CHART_POINTS)
        self.assertGreater(drawn, 2)
        # The samples kept are the first and last record, so the stated span is
        # still the span the window holds.
        self.assertIn(f"900 条 · 2026-06-01 至 2026-08-30", html)
        self.assertEqual(html.count("<circle"), 1)          # only the latest point is dotted
        self.assertIn(f"另有 {900 - drawn} 条记录未绘入图表", html)

    def test_a_short_series_is_drawn_in_full_with_no_omission_note(self):
        html = briefing_report._metric_trend_section({"heart_rate": self._points([70, 78, 74])}, "zh-CN")

        self.assertEqual(html.count("<circle"), 3)
        self.assertNotIn("未绘入图表", html)

    def test_the_wide_slot_goes_to_the_first_chartable_metric_not_the_first_listed(self):
        """A value line sorts first but cannot hold a chart slot it has no chart for."""
        html = briefing_report._metric_trend_section(
            {"blood_oxygen": [{"value": "—", "date": "2026-09-01", "source": "manual", "metric_type": "blood_oxygen"},
                              {"value": "—", "date": "2026-09-08", "source": "manual", "metric_type": "blood_oxygen"},
                              {"value": "—", "date": "2026-09-09", "source": "manual", "metric_type": "blood_oxygen"}],
             "heart_rate": self._points([70, 78])}, "zh-CN")

        self.assertEqual(html.count('class="trend-chart'), 1)
        self.assertEqual(html.count("trend-chart wide"), 1)
        # The value line is listed first; the heart-rate chart follows it and is
        # the one drawn full width.
        self.assertLess(html.index("血氧"), html.index("trend-chart"))
        self.assertIn('<article class="trend-chart wide"><div class="trend-head"><b>心率</b>', html)

    def test_other_metrics_carry_no_legend(self):
        html = briefing_report._metric_trend_section({"heart_rate": self._points([70, 78])}, "zh-CN")

        self.assertIn("心率", html)
        self.assertNotIn("收缩压", html)
        self.assertEqual(html.count("<polyline"), 1)

    def test_a_blank_reading_is_skipped_rather_than_plotted_as_zero(self):
        html = briefing_report._metric_trend_section(
            {"blood_pressure": [{"date": "2026-09-01", "source": "manual", "systolic": 148, "diastolic": 92},
                                {"date": "2026-09-05", "source": "manual", "systolic": None, "diastolic": None},
                                {"date": "2026-09-08", "source": "manual", "systolic": 133, "diastolic": 80}]},
            "zh-CN")

        self.assertEqual(len(self._xs(html)), 4)
        self.assertNotIn(">0<", html)

    def test_a_metric_with_no_plottable_number_falls_back_to_the_value_line(self):
        html = briefing_report._metric_trend_section(
            {"blood_pressure": [{"date": "2026-09-01", "source": "manual", "systolic": "—", "diastolic": "—"},
                                {"date": "2026-09-08", "source": "manual", "systolic": "—", "diastolic": "—"}]},
            "zh-CN")

        self.assertNotIn("<svg", html)
        self.assertIn('class="trend-single"', html)

    def test_same_day_records_are_laid_out_in_order_and_do_not_overlap(self):
        """No date offset exists, so the points are spaced by record order."""
        points = [{"value": value, "date": "2026-09-08", "source": "manual", "metric_type": "heart_rate"}
                  for value in (70, 78, 74)]

        html = briefing_report._metric_trend_section({"heart_rate": points}, "zh-CN")

        xs = self._xs(html)
        self.assertIn('<svg class="chart"', html)
        self.assertEqual(len(xs), 3)
        self.assertEqual(xs, sorted(set(xs)))
        # One date, said once -- not the same label printed under every point.
        self.assertEqual(html.count(">09-08</text>"), 1)

    def test_the_same_records_always_draw_the_same_picture(self):
        trends = {"blood_pressure": [{"date": "2026-09-01", "source": "manual", "systolic": 148, "diastolic": 92},
                                     {"date": "2026-09-08", "source": "manual", "systolic": 133, "diastolic": 80}]}

        self.assertEqual(briefing_report._metric_trend_section(trends, "zh-CN"),
                         briefing_report._metric_trend_section(trends, "zh-CN"))

    def test_only_the_first_chart_is_drawn_full_width(self):
        html = briefing_report._metric_trend_section(
            {"weight": self._points([70.0, 71.0], metric_type="weight"),
             "heart_rate": self._points([70, 78]),
             "blood_oxygen": self._points([96, 97], metric_type="blood_oxygen")}, "zh-CN")

        self.assertEqual(html.count("trend-chart wide"), 1)
        self.assertEqual(html.count('class="trend-chart"'), 2)
        # The full-width chart is the first one drawn.
        self.assertLess(html.index("trend-chart wide"), html.index('class="trend-chart"'))

    def test_the_chart_never_draws_a_reference_range_or_a_verdict(self):
        html = briefing_report._metric_trend_section(
            {"blood_pressure": [{"date": "2026-09-01", "source": "manual", "systolic": 148, "diastolic": 92},
                                {"date": "2026-09-08", "source": "manual", "systolic": 133, "diastolic": 80}]},
            "zh-CN")

        for word in ("参考", "正常", "异常", "偏高", "偏低", "range", "normal", "abnormal", "high", "low"):
            self.assertNotIn(word, html)
        self.assertLessEqual(set(re.findall(r'(?:fill|stroke)="(#[0-9A-F]{6})"', html)), self.PALETTE)

    def test_a_value_is_painted_the_same_whatever_its_magnitude(self):
        """Colour says which series a point belongs to, never what it reads."""
        inside = briefing_report._chart_svg("heart_rate", self._points([70, 72]),
                                            briefing_report._metric_series("heart_rate", self._points([70, 72])),
                                            "zh-CN", True)
        outside = briefing_report._chart_svg("heart_rate", self._points([160, 168]),
                                             briefing_report._metric_series("heart_rate", self._points([160, 168])),
                                             "zh-CN", True)

        self.assertEqual(set(re.findall(r"(?:fill|stroke)=\"(#[0-9A-F]{6})\"", inside)),
                         set(re.findall(r"(?:fill|stroke)=\"(#[0-9A-F]{6})\"", outside)))
        self.assertNotIn("<rect", inside)

    def test_no_series_is_painted_in_the_alert_tone(self):
        """Coral means "flagged" everywhere else on this card."""
        self.assertNotIn("#D66548", briefing_report.SERIES_COLORS)
        html = briefing_report._metric_trend_section(
            {"blood_pressure": [{"date": "2026-09-01", "source": "manual", "systolic": 148, "diastolic": 92},
                                {"date": "2026-09-08", "source": "manual", "systolic": 133, "diastolic": 80}]},
            "zh-CN")

        self.assertNotIn("#D66548", html)

        for word in ("参考", "正常", "异常", "偏高", "偏低", "range", "normal", "abnormal", "high", "low"):
            self.assertNotIn(word, html)
        self.assertLessEqual(set(re.findall(r'(?:fill|stroke)="(#[0-9A-F]{6})"', html)), self.PALETTE)

    def test_an_axis_covers_the_recorded_range(self):
        points = self._points([70.0, 73.0], metric_type="weight")
        svg = briefing_report._chart_svg("weight", points,
                                         briefing_report._metric_series("weight", points), "zh-CN", True)

        self.assertIn(f'viewBox="0 0 {briefing_report.CHART_WIDE} {briefing_report.CHART_HEIGHT}"', svg)
        self.assertIn("<line", svg)
        for value in ("70.0", "73.0"):
            self.assertIn(f">{value}</text>", svg)

    def test_a_quarter_step_is_not_used_where_no_label_could_state_it(self):
        """0.25 steps would print "6.2" on a line drawn at 6.25."""
        ticks, step = briefing_report._axis_ticks([6.8, 6.5, 6.6, 6.2, 6.4, 5.9])

        self.assertEqual(step, 0.5)
        self.assertEqual(ticks, [5.5, 6.0, 6.5, 7.0])

    def test_every_tick_label_states_the_line_it_sits_on(self):
        for numbers in ([6.8, 6.5, 6.6, 6.2, 6.4, 5.9], [96.0, 97.0], [36.4, 36.5], [74.8, 78.5]):
            ticks, step = briefing_report._axis_ticks(numbers)
            digits = briefing_report._tick_digits(step)
            for tick in ticks:
                label = briefing_report._fmt_number(tick, digits).replace(",", "")
                self.assertEqual(float(label), tick, (numbers, ticks))


class SummaryStripTest(unittest.TestCase):
    def test_each_figure_counts_one_thing(self):
        html = briefing_report._summary_strip(
            {"total_alerts": 2, "total_warnings": 1, "total_abnormal": 6, "total_due_reminders": 0}, "zh-CN")

        self.assertIn("2 项警告", html)
        self.assertIn("1 项提醒", html)
        self.assertIn("6 项明确异常", html)
        self.assertNotIn("7 项提醒", html)

    def test_flagged_labs_alone_still_produce_a_strip(self):
        html = briefing_report._summary_strip(
            {"total_alerts": 0, "total_warnings": 0, "total_abnormal": 6, "total_due_reminders": 0}, "zh-CN")

        self.assertIn("6 项明确异常", html)
        self.assertNotIn("hero-clear", html)

    def test_nothing_to_report_shows_the_clear_state(self):
        html = briefing_report._summary_strip(
            {"total_alerts": 0, "total_warnings": 0, "total_abnormal": 0, "total_due_reminders": 0}, "zh-CN")

        self.assertIn("hero-clear", html)


class AgeResolutionTest(unittest.TestCase):
    def test_a_birth_date_is_exact_and_a_recorded_age_is_approximate(self):
        age, approximate = metric_utils.resolve_age("1980-05-04")
        self.assertIsInstance(age, int)
        self.assertFalse(approximate)

        age, approximate = metric_utils.resolve_age(None, 89, "2026-09-08")
        self.assertEqual(age, 89)
        self.assertTrue(approximate)

    def test_birth_date_wins_when_both_are_recorded(self):
        age, approximate = metric_utils.resolve_age("1980-05-04", 20, "2026-09-08")

        self.assertNotEqual(age, 20)
        self.assertFalse(approximate)

    def test_a_recorded_age_advances_with_the_calendar(self):
        age, approximate = metric_utils.resolve_age(None, 89, "2024-01-01")

        self.assertEqual(age, 91)
        self.assertTrue(approximate)

    def test_nothing_recorded_stays_unknown(self):
        self.assertEqual(metric_utils.resolve_age(None), (None, False))
        self.assertEqual(metric_utils.resolve_age(None, "不详"), (None, False))
        self.assertEqual(metric_utils.resolve_age(None, 200, "2026-09-08"), (None, False))

    def test_header_shows_sex_and_age_only_when_recorded(self):
        exact = briefing_report._identity_text(
            {"gender": "男", "birth_date": "1980-05-04", "age_years": None}, "zh-CN")
        self.assertTrue(exact.startswith("男 · "))
        self.assertTrue(exact.endswith(" 岁"))

        approximate = briefing_report._identity_text(
            {"gender": "男", "age_years": 89, "age_recorded_at": "2026-09-08"}, "zh-CN")
        self.assertEqual(approximate, "男 · 89 岁（2026-09-08 记录）")

        self.assertEqual(briefing_report._identity_text({"name": "无资料"}, "zh-CN"), "")

    def test_sex_is_never_inferred_from_the_name(self):
        self.assertEqual(briefing_report._identity_text({"name": "张建国"}, "zh-CN"), "")


class SnapshotLayoutContractTest(unittest.TestCase):
    def test_layout_profile_describes_the_block(self):
        profile = briefing_report._snapshot_profile(
            {"medical_history": "高血压", "allergies": ""},
            {"diagnoses": [{"diagnosis": "高血压"}],
             "abnormal_reports": [{"items": [{"name": "FPG"}, {"name": "TC"}]}]},
            {"health_tips": [{"type": "metric_anomaly", "severity": "alert", "title": "血压高于配置范围"},
                             {"type": "metric_gap", "severity": "info", "title": "血压已 4 天未测量"}]},
        )

        self.assertEqual(profile, {
            "diagnosis_count": 1, "report_count": 1, "abnormal_item_count": 2,
            "threshold_count": 1, "has_history": True, "has_allergies": False,
        })

    def test_an_alert_with_nothing_to_show_is_not_counted(self):
        """The profile must describe the block as drawn, not the raw tip list."""
        member_data = {"health_tips": [
            {"type": "metric_anomaly", "severity": "alert", "title": "血压高于配置范围"},
            {"type": "metric_anomaly", "severity": "alert"},
        ]}
        snapshot = {"diagnoses": [], "abnormal_reports": []}

        profile = briefing_report._snapshot_profile({}, snapshot, member_data)
        html = briefing_report._snapshot_section({}, snapshot, member_data, "zh-CN")

        self.assertEqual(profile["threshold_count"], 1)
        self.assertEqual(html.count('class="snapshot-threshold '), 1)


class MetricSectionAvailabilityTest(unittest.TestCase):
    """The section draws the chart series, so that is what decides it is shown."""

    MEMBER_DATA = {"health_tips": [], "due_reminders": []}
    CARE = {"visits": [], "labs": [], "imaging": []}

    def test_a_series_inside_the_chart_window_keeps_the_section(self):
        # trends={} is the card's own window; the chart window is the only place
        # the measurements sit, and the section must still be drawn.
        layout = briefing_report._personal_layout(
            self.MEMBER_DATA, {}, {}, {}, self.CARE, [],
            chart_trends={"weight": [{"value": 70.0, "date": "2026-06-01"},
                                     {"value": 71.0, "date": "2026-06-02"}]})

        self.assertIn("metrics", layout["section_order"])
        # Coverage still counts the card's own window: the layout score must not
        # move just because the charts look further back.
        self.assertEqual(layout["coverage"]["metrics"], 0)

    def test_with_no_records_at_all_only_the_fallback_section_remains(self):
        """An empty card still renders one section; availability decides which."""
        layout = briefing_report._personal_layout(
            self.MEMBER_DATA, {}, {}, {}, self.CARE, [])

        self.assertEqual(layout["section_order"], ["metrics"])
        self.assertEqual(layout["coverage"]["metrics"], 0)


class HealthCardThemeTest(unittest.TestCase):
    def test_health_card_uses_blue_visual_system(self):
        html = briefing_report._render_html(
            "健康卡片", "最近 7 天", "个人本地档案", "", "", "zh-CN"
        )

        self.assertIn("--page:#F3F7FC", html)
        self.assertIn("--primary:#246BCE", html)
        self.assertIn("linear-gradient(135deg,#0A2F55,#155E9E)", html)
        self.assertIn(".family-grid>.family-card:nth-child(odd):last-child", html)
        self.assertNotIn("linear-gradient(135deg,#123C35,#1A6B5E)", html)

    def test_health_card_uses_readable_typography(self):
        html = briefing_report._render_html(
            "健康卡片", "最近 7 天", "个人本地档案", "", "", "zh-CN"
        )

        self.assertIn('font:16px/1.65', html)
        self.assertIn('h1{font-size:32px', html)
        self.assertIn('.big{font-size:28px', html)
        self.assertIn('.chart{display:block;width:100%', html)
        self.assertIn('.family-list-item.medication b{font-size:13px', html)
        self.assertNotIn('font-size:8px', html)
        self.assertNotIn('font-size:9px', html)
        self.assertNotIn('font-size:10px', html)

    def test_metric_charts_use_blue_as_the_default(self):
        points = [{"value": 70, "date": "2026-07-20", "metric_type": "heart_rate"},
                  {"value": 72, "date": "2026-07-21", "metric_type": "heart_rate"}]
        svg = briefing_report._chart_svg(
            "heart_rate", points, briefing_report._metric_series("heart_rate", points), "zh-CN", False)

        self.assertIn(briefing_report.SERIES_COLORS[0], svg)
        self.assertNotIn("#1E7A6E", svg)
        self.assertIn('viewBox="0 0 460 250"', svg)


if __name__ == "__main__":
    unittest.main()
