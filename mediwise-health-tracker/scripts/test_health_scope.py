"""Regression checks for MediWise's non-medical-guidance boundary."""

from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPTS_DIR.parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import cycle_tracker


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class HealthScopeRegressionTests(unittest.TestCase):
    def test_cycle_status_exposes_no_care_or_medication_tips(self):
        self.assertEqual(cycle_tracker.CARE_TIPS, {})

    def test_sleep_score_only_describes_reference_differences(self):
        sleep = _load_module(
            "mediwise_sleep_scope_test",
            ROOT_DIR / "sleep-tracker" / "scripts" / "sleep.py",
        )
        result = sleep._quality_score({
            "duration_min": 300,
            "deep_min": 20,
            "light_min": 220,
            "rem_min": 20,
            "awake_min": 40,
        })

        self.assertIn(result["label"], {"高匹配", "较高匹配", "部分匹配", "低匹配"})
        joined = " ".join(result["issues"])
        self.assertIn("内置参考", joined)
        self.assertNotIn("建议", joined)
        self.assertNotIn("需要干预", joined)

    def test_monitor_priority_labels_are_not_clinical_judgments(self):
        monitor_scripts = ROOT_DIR / "health-monitor" / "scripts"
        if str(monitor_scripts) not in sys.path:
            sys.path.insert(0, str(monitor_scripts))
        dashboard = _load_module(
            "mediwise_dashboard_scope_test",
            monitor_scripts / "dashboard.py",
        )

        self.assertEqual(dashboard._risk_label("normal"), "无阈值提醒")
        self.assertEqual(dashboard._risk_label("urgent"), "高优先级")
        self.assertEqual(dashboard._risk_label("emergency"), "最高优先级")

    def test_calorie_suggestion_endpoint_declines_to_prescribe_target(self):
        body_stats = _load_module(
            "mediwise_body_stats_scope_test",
            ROOT_DIR / "weight-manager" / "scripts" / "body_stats.py",
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            body_stats.suggest_calories(SimpleNamespace(member_id="member-test"))

        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "unsupported")
        self.assertIsNone(result["suggested_daily_calories"])
        self.assertIn("不生成", result["message"])

    def test_runtime_outputs_do_not_reintroduce_prescriptive_phrases(self):
        runtime_files = [
            SCRIPTS_DIR / "health_advisor.py",
            SCRIPTS_DIR / "cycle_tracker.py",
            ROOT_DIR / "diet-tracker" / "scripts" / "nutrition.py",
            ROOT_DIR / "weight-manager" / "scripts" / "weight_analysis.py",
            ROOT_DIR / "weight-manager" / "scripts" / "weight_truth_card.py",
            ROOT_DIR / "weight-manager" / "scripts" / "weight_story_card.py",
            ROOT_DIR / "weight-manager" / "scripts" / "weight_style_selector.py",
            ROOT_DIR / "weight-manager" / "scripts" / "weight_goal.py",
            ROOT_DIR / "weight-manager" / "scripts" / "body_stats.py",
            ROOT_DIR / "sleep-tracker" / "scripts" / "sleep.py",
        ]
        forbidden = [
            "建议增加鱼肉蛋奶",
            "建议减少油炸",
            "建议尽快就医复查",
            "建议增加热量摄入",
            "建议每周至少运动",
            "注意保暖和休息",
            "避免剧烈运动",
            "提前准备抗过敏药物",
        ]

        combined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
        for phrase in forbidden:
            self.assertNotIn(phrase, combined)


if __name__ == "__main__":
    unittest.main()
