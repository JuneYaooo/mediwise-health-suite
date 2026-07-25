from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "weight-manager" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import weight_truth_card
from weight_management_analysis import analyze_weight_management


END = date(2026, 7, 30)
START = END - timedelta(days=29)


def weight_analysis():
    records = [
        {
            "value": 72.0 - index * 0.04,
            "measured_at": (START + timedelta(days=index)).isoformat() + " 08:00:00",
        }
        for index in range(30)
    ]
    return weight_truth_card.analyze_weight_records(records, 30)


class WeightManagementAnalysisTests(unittest.TestCase):
    def test_unrecorded_diet_days_are_not_treated_as_zero(self):
        diet = [
            {"meal_date": (START + timedelta(days=index)).isoformat(), "total_calories": value}
            for index, value in ((0, 1800), (2, 1900), (5, 2000))
        ]
        result = analyze_weight_management(weight_analysis(), diet, [], [], days=30, as_of=END)
        intake = result["intake"]

        self.assertEqual(intake["recorded_days"], 3)
        self.assertEqual(intake["average_calories_on_recorded_days"], 1900)
        self.assertFalse(intake["missing_days_are_zero"])
        self.assertIn("未记录日也不能按零摄入", result["synthesis"]["paragraph"])

    def test_zero_default_fields_do_not_become_a_zero_calorie_day(self):
        diet = [
            {"meal_date": (START + timedelta(days=index)).isoformat(), "total_calories": value}
            for index, value in ((0, 1800), (1, 0), (2, 1900), (3, 2000))
        ]
        result = analyze_weight_management(weight_analysis(), diet, [], [], days=30, as_of=END)

        self.assertEqual(result["intake"]["recorded_days"], 4)
        self.assertEqual(result["intake"]["calorie_recorded_days"], 3)
        self.assertEqual(result["intake"]["average_calories_on_recorded_days"], 1900)

    def test_domain_thresholds_and_half_comparisons(self):
        diet = []
        sleep = []
        exercise = []
        for offset in (1, 4, 8, 17, 21, 26):
            second = offset >= 15
            day = (START + timedelta(days=offset)).isoformat()
            diet.append({"meal_date": day, "total_calories": 1800 if second else 1950})
            sleep.append({"measured_at": day + " 07:00:00", "value": {"duration_min": 450 if second else 410}})
        for offset in (3, 10, 18, 25):
            exercise.append({
                "exercise_date": (START + timedelta(days=offset)).isoformat(),
                "duration": 60 if offset >= 15 else 30,
                "calories_burned": 260,
            })

        result = analyze_weight_management(weight_analysis(), diet, exercise, sleep, days=30, as_of=END)

        self.assertEqual(result["intake"]["change_calories"], -150)
        self.assertEqual(result["activity"]["change_duration_min"], 60)
        self.assertEqual(result["sleep"]["change_min"], 40)
        self.assertEqual(result["coverage"]["eligible_lifestyle_domains"], 3)
        self.assertEqual(result["coverage"]["overall_label"], "较完整")
        self.assertEqual(result["synthesis"]["situation"]["pattern_id"], "second-half-shift")
        self.assertEqual(result["synthesis"]["situation"]["title"], "后半场换挡")
        self.assertIn("摄入平均值−150 kcal", result["synthesis"]["situation"]["summary"])
        self.assertIn("运动总时长+60 分钟", result["synthesis"]["situation"]["summary"])
        self.assertIn("睡眠记录平均时长+40 分钟", result["synthesis"]["situation"]["summary"])
        self.assertEqual(result["synthesis"]["social_packaging"]["cover_hook"], "后半场换挡")
        self.assertIn("result_first", result["synthesis"]["social_packaging"]["hook_mechanisms"])
        self.assertIn("保存这张", result["synthesis"]["social_packaging"]["save_prompt"])
        self.assertFalse(result["synthesis"]["social_packaging"]["clickbait"])

    def test_sparse_halves_do_not_claim_change(self):
        diet = [
            {"meal_date": START.isoformat(), "total_calories": 1900},
            {"meal_date": END.isoformat(), "total_calories": 1700},
        ]
        result = analyze_weight_management(weight_analysis(), diet, [], [], days=30, as_of=END)

        self.assertFalse(result["intake"]["claim_allowed"])
        self.assertIsNone(result["intake"]["change_calories"])
        self.assertIn("尚不足以比较", result["synthesis"]["paragraph"])

    def test_copy_never_turns_parallel_signals_into_cause_or_deficit(self):
        diet = []
        exercise = []
        sleep = []
        for index in range(20):
            day = (START + timedelta(days=index)).isoformat()
            diet.append({"meal_date": day, "total_calories": 1900 - index * 4})
            sleep.append({"measured_at": day, "value": {"duration_min": 420 + index}})
            if index % 2 == 0:
                exercise.append({"exercise_date": day, "duration": 35 + index, "calories_burned": 200})
        result = analyze_weight_management(weight_analysis(), diet, exercise, sleep, days=30, as_of=END)
        all_copy = str(result)

        self.assertFalse(result["synthesis"]["causal_claim"])
        self.assertFalse(result["synthesis"]["prescription"])
        self.assertFalse(result["activity"]["burn_is_total_expenditure"])
        for forbidden in ("导致体重", "造成减重", "热量缺口为", "建议少吃", "增加运动", "促进减脂"):
            self.assertNotIn(forbidden, all_copy)
        self.assertIn("不能证明它们造成了体重变化", result["synthesis"]["paragraph"])

    def test_latest_scale_plot_twist_becomes_a_grounded_memorable_hook(self):
        values = [71.0, 70.8, 70.7, 70.6, 70.5, 70.4, 70.3, 70.2, 70.1, 70.0, 69.9, 70.8]
        records = [
            {"value": value, "measured_at": (START + timedelta(days=index)).isoformat()}
            for index, value in enumerate(values)
        ]
        weight = weight_truth_card.analyze_weight_records(records, 30)
        result = analyze_weight_management(weight, [], [], [], days=30, as_of=END)
        situation = result["synthesis"]["situation"]

        self.assertEqual(situation["pattern_id"], "scale-plot-twist")
        self.assertEqual(situation["title"], "今天抢镜，长线没改剧本")
        self.assertIn("最新一次秤面上浮", situation["summary"])
        self.assertIn("contrarian", result["synthesis"]["social_packaging"]["hook_mechanisms"])

    def test_sparse_data_stays_interesting_without_inventing_a_story(self):
        result = analyze_weight_management(weight_analysis(), [], [], [], days=30, as_of=END)
        situation = result["synthesis"]["situation"]

        self.assertEqual(situation["pattern_id"], "loading-signals")
        self.assertEqual(situation["title"], "线索还在加载")
        self.assertIn("生活方式记录还不足", situation["hook"])
        self.assertEqual(situation["changed_domains"], [])
        self.assertTrue(situation["non_judgemental"])


if __name__ == "__main__":
    unittest.main()
