import sys
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
