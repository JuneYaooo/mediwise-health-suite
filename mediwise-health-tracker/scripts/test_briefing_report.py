import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import briefing_report


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


class HealthCardThemeTest(unittest.TestCase):
    def test_health_card_uses_blue_visual_system(self):
        html = briefing_report._render_html(
            "健康记录卡片", "最近 7 天", "个人本地档案", "", "", "zh-CN"
        )

        self.assertIn("--page:#F3F7FC", html)
        self.assertIn("--primary:#246BCE", html)
        self.assertIn("linear-gradient(135deg,#0A2F55,#155E9E)", html)
        self.assertIn(".family-grid>.family-card:nth-child(odd):last-child", html)
        self.assertNotIn("linear-gradient(135deg,#123C35,#1A6B5E)", html)

    def test_health_card_uses_readable_typography(self):
        html = briefing_report._render_html(
            "健康记录卡片", "最近 7 天", "个人本地档案", "", "", "zh-CN"
        )

        self.assertIn('font:16px/1.65', html)
        self.assertIn('h1{font-size:32px', html)
        self.assertIn('.metric-value{font-size:28px', html)
        self.assertIn('.family-list-item.medication b{font-size:13px', html)
        self.assertNotIn('font-size:8px', html)
        self.assertNotIn('font-size:9px', html)
        self.assertNotIn('font-size:10px', html)

    def test_metric_sparklines_use_blue_as_the_default(self):
        html = briefing_report._sparkline(
            "heart_rate",
            [
                {"value": 70, "date": "2026-07-20"},
                {"value": 72, "date": "2026-07-21"},
            ],
            "zh-CN",
        )

        self.assertIn("#246BCE", html)
        self.assertNotIn("#1E7A6E", html)


class PersonalHealthStoryTest(unittest.TestCase):
    def _sleep_story(self):
        sleep = {
            "count": 7,
            "daily_records": [
                {"date": f"2026-07-{day:02d}", "duration_min": 390 + day * 8}
                for day in range(1, 8)
            ],
        }
        lifestyle = {"diet_records": [], "step_records": [], "exercise_records": []}
        return briefing_report._build_personal_story("member-1", {}, lifestyle, sleep, 7)

    def test_story_row_shaper_leaves_domain_folding_to_adapters(self):
        trends = {
            "weight": [
                {"date": "2026-07-01", "value": 70.0},
                {"date": "2026-07-01", "value": 72.0},
            ],
            "heart_rate": [{"date": "2026-07-01", "value": 71}],
        }
        lifestyle = {
            "diet_records": [],
            "step_records": [
                {"metric_type": "steps", "measured_at": "2026-07-01 08:00:00", "value": {"count": 1000}},
                {"metric_type": "steps", "measured_at": "2026-07-01 20:00:00", "value": {"count": 2200}},
            ],
        }
        rows = briefing_report._story_rows(trends, lifestyle, {"daily_records": []})

        self.assertEqual(rows["weight"][0]["weight"], 71.0)
        self.assertEqual(rows["weight"][0]["measurement_count"], 2)
        self.assertEqual(rows["vitals"][0]["metric_type"], "heart_rate")
        self.assertEqual(len(rows["activity"]), 2)

        api = briefing_report._story_api()
        analysis = api["domain_analysis_from_rows"]("activity", rows["activity"], 7)
        ready = api["render_ready"]("activity", analysis)
        self.assertEqual(len(ready["frame"]["series"]), 1)
        self.assertEqual(ready["frame"]["series"][0]["value"], 2200.0)

    def test_story_builder_selects_and_fits_a_recorded_domain(self):
        story = self._sleep_story()

        self.assertIsNotNone(story)
        self.assertEqual(story["domain"], "sleep")
        self.assertEqual(story["frame"]["series_meta"]["fold"], "mean")
        self.assertEqual(story["frame"]["trend"]["method"], "theil_sen")
        self.assertIsNotNone(story["selection"]["selected_style"]["id"])
        svg = briefing_report._personal_story_svg(story)
        self.assertIn("<svg", svg)
        self.assertIn("MediWise 睡眠译报", svg)
        self.assertIn('data-story-domain="sleep"', svg)
        self.assertIn('data-motion-mode="', svg)
        self.assertIn('data-duration-ms="', svg)
        self.assertNotIn('data-duration-ms="0"', svg)

    def test_story_bundle_keeps_every_recorded_domain_for_video(self):
        trends = {
            "weight": [
                {"date": f"2026-07-{day:02d}", "value": 70 + day / 10}
                for day in range(1, 8)
            ],
            "heart_rate": [
                {"date": f"2026-07-{day:02d}", "value": 68 + day}
                for day in range(1, 8)
            ],
        }
        sleep = {
            "daily_records": [
                {"date": f"2026-07-{day:02d}", "duration_min": 390 + day * 8}
                for day in range(1, 8)
            ]
        }
        lifestyle = {
            "diet_records": [
                {"meal_date": f"2026-07-{day:02d}", "total_calories": 1600 + day * 20}
                for day in range(1, 8)
            ],
            "step_records": [
                {"metric_type": "steps", "measured_at": f"2026-07-{day:02d} 20:00:00", "value": {"count": 5000 + day * 200}}
                for day in range(1, 8)
            ],
        }

        stories = briefing_report._build_personal_stories(
            "member-1", trends, lifestyle, sleep, 7
        )

        self.assertEqual(
            [story["domain"] for story in stories],
            ["weight", "sleep", "vitals", "intake", "activity"],
        )
        self.assertTrue(all(story["frame"]["series"] for story in stories))
        self.assertTrue(all(story["selection"]["selected_style"]["id"] for story in stories))

    def test_story_builder_skips_one_malformed_domain(self):
        api = briefing_report._story_api()
        analyze = api["domain_analysis_from_rows"]

        def fail_weight_only(domain, rows, days):
            if domain == "weight":
                raise ValueError("malformed legacy weight stream")
            return analyze(domain, rows, days)

        trends = {
            "weight": [
                {"date": f"2026-07-{day:02d}", "value": 70 + day / 10}
                for day in range(1, 8)
            ]
        }
        sleep = {
            "count": 7,
            "daily_records": [
                {"date": f"2026-07-{day:02d}", "duration_min": 390 + day * 8}
                for day in range(1, 8)
            ],
        }
        lifestyle = {"diet_records": [], "step_records": [], "exercise_records": []}

        with self.assertLogs(briefing_report.LOG, level="WARNING") as logs:
            with patch.dict(api, {"domain_analysis_from_rows": fail_weight_only}):
                story = briefing_report._build_personal_story(
                    "member-1", trends, lifestyle, sleep, 7
                )

        self.assertIsNotNone(story)
        self.assertEqual(story["domain"], "sleep")
        self.assertIn("skipped weight domain", "\n".join(logs.output))

    def test_story_is_a_real_fifth_layout_section_in_both_locales(self):
        story = self._sleep_story()
        member_data = {"health_tips": [], "due_reminders": []}
        lifestyle = {"diet_days": 0, "exercise_count": 0, "step_days": 0}
        sleep = {"count": 7}
        care = {"visits": [], "labs": [], "imaging": [], "record_counts": {}}
        layout = briefing_report._personal_layout(
            member_data, {}, lifestyle, sleep, care, [], "story", story=story
        )

        self.assertEqual(layout["section_order"][0], "story")
        zh = briefing_report._personal_content(
            {"id": "member-1"}, member_data, {}, lifestyle, sleep, care, [],
            "zh-CN", layout, story=story,
        )
        en = briefing_report._personal_content(
            {"id": "member-1"}, member_data, {}, lifestyle, sleep, care, [],
            "en-US", layout, story=story,
        )
        self.assertIn("个人健康译报", zh)
        self.assertIn('data-story-domain="sleep"', zh)
        self.assertIn("Personal Health Story", en)
        self.assertIn("sleep duration", en)

    def test_no_recorded_domain_means_no_story_section(self):
        story = briefing_report._build_personal_story(
            "member-1", {}, {"diet_records": [], "step_records": []}, {"daily_records": []}, 7
        )
        self.assertIsNone(story)


if __name__ == "__main__":
    unittest.main()
