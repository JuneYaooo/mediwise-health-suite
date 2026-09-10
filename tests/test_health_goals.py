"""End-to-end contracts for user-confirmed goals and meaning-gated evidence cards."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MEMBER = ROOT / "mediwise-health-tracker" / "scripts" / "member.py"
GOAL = ROOT / "health-goals" / "scripts" / "goal.py"
CARD = ROOT / "health-goals" / "scripts" / "goal_card.py"
EXERCISE = ROOT / "weight-manager" / "scripts" / "exercise.py"


class HealthGoalsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        self.env["MEDIWISE_DATA_DIR"] = self.temp.name
        self.env["MEDIWISE_SINGLE_USER"] = "1"
        created = self.run_json(MEMBER, "add", "--name", "测试成员", "--relation", "本人")
        self.assertEqual(created["status"], "ok")
        self.member_id = created["member"]["id"]

    def tearDown(self):
        self.temp.cleanup()

    def run_json(self, script: Path, *args: str) -> dict:
        completed = subprocess.run(
            [sys.executable, str(script), *map(str, args)],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(completed.stdout)

    def create_goal(self, goal_type="weekly_frequency", target=3, total_periods=4, title="每周运动三次"):
        args = [
            "create", "--member-id", self.member_id, "--domain", "activity",
            "--goal-type", goal_type, "--title", title, "--target-value", str(target),
            "--start-date", "2026-06-01", "--confirmed",
        ]
        if total_periods is not None:
            args.extend(["--total-periods", str(total_periods)])
        return self.run_json(GOAL, *args)

    def test_confirmation_is_required_and_only_one_active_goal_per_domain(self):
        rejected = self.run_json(
            GOAL, "create", "--member-id", self.member_id, "--domain", "activity",
            "--goal-type", "weekly_frequency", "--title", "每周走路三次",
            "--target-value", "3",
        )
        self.assertEqual(rejected["status"], "error")
        self.assertIn("明确确认", rejected["message"])

        first = self.create_goal()
        self.assertEqual(first["status"], "ok")
        second = self.create_goal(title="另一个活动目标")
        self.assertEqual(second["status"], "error")
        self.assertEqual(second["existing_goal_id"], first["goal"]["id"])

    def test_frequency_progress_source_idempotency_and_milestone_idempotency(self):
        goal_id = self.create_goal()["goal"]["id"]
        first = self.run_json(
            GOAL, "checkin", "--goal-id", goal_id, "--occurred-at", "2026-07-27",
            "--source-record-type", "exercise_record", "--source-record-id", "exercise-1",
        )
        duplicate = self.run_json(
            GOAL, "checkin", "--goal-id", goal_id, "--occurred-at", "2026-07-27",
            "--source-record-type", "exercise_record", "--source-record-id", "exercise-1",
        )
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["progress"]["checkin_count"], 1)
        self.assertEqual(first["new_milestones"], [])
        self.assertFalse(first["feedback"]["card_available"])

        for day in ("2026-07-29", "2026-08-01"):
            latest = self.run_json(GOAL, "checkin", "--goal-id", goal_id, "--occurred-at", day)
        self.assertEqual(latest["progress"]["current_value"], 3)
        self.assertEqual(latest["progress"]["overall_ratio"], 0.25)
        kinds = {item["milestone_type"] for item in latest["new_milestones"]}
        self.assertEqual(kinds, {"rhythm"})
        self.assertTrue(latest["feedback"]["card_available"])

        before = self.run_json(GOAL, "milestones", "--goal-id", goal_id)
        self.run_json(GOAL, "progress", "--goal-id", goal_id, "--as-of", "2026-08-01")
        after = self.run_json(GOAL, "milestones", "--goal-id", goal_id)
        self.assertEqual(before["count"], after["count"])
        self.assertEqual({item["milestone_key"] for item in after["milestones"]},
                         {"rhythm-established"})
        evidence = after["milestones"][0]["evidence"]
        self.assertEqual(evidence["schema_version"], 2)
        self.assertEqual(evidence["checkin_count"], 3)
        self.assertEqual([item["date"] for item in evidence["action_days"]],
                         ["2026-07-27", "2026-07-29", "2026-08-01"])

    def test_duration_cumulative_completion_keeps_one_meaning_per_action(self):
        duration = self.create_goal(
            goal_type="weekly_duration", target=90, total_periods=2, title="每周运动九十分钟"
        )
        duration_id = duration["goal"]["id"]
        self.run_json(GOAL, "checkin", "--goal-id", duration_id,
                      "--occurred-at", "2026-06-02", "--duration-minutes", "45")
        result = self.run_json(GOAL, "checkin", "--goal-id", duration_id,
                               "--occurred-at", "2026-06-04", "--duration-minutes", "45")
        self.assertEqual(result["progress"]["current_value"], 90)

        self.run_json(GOAL, "status", "--goal-id", duration_id, "--status", "abandoned")
        cumulative = self.create_goal(
            goal_type="cumulative_count", target=2, total_periods=None, title="完成两次训练"
        )
        cumulative_id = cumulative["goal"]["id"]
        self.run_json(GOAL, "checkin", "--goal-id", cumulative_id, "--occurred-at", "2026-07-01")
        finished = self.run_json(GOAL, "checkin", "--goal-id", cumulative_id,
                                 "--occurred-at", "2026-07-20")
        self.assertEqual(finished["progress"]["status"], "completed")
        self.assertEqual(finished["progress"]["overall_ratio"], 1.0)
        milestones = self.run_json(GOAL, "milestones", "--goal-id", cumulative_id)
        self.assertEqual({item["milestone_type"] for item in milestones["milestones"]},
                         {"completion"})
        self.assertEqual({item["milestone_key"] for item in milestones["milestones"]},
                         {"completion"})

    def test_return_after_gap_is_a_recovery_card_when_completion_does_not_mask_it(self):
        goal = self.create_goal(
            goal_type="cumulative_count", target=10, total_periods=None,
            title="完成十次训练",
        )
        goal_id = goal["goal"]["id"]
        for day in ("2026-07-01", "2026-07-02", "2026-07-03"):
            self.run_json(GOAL, "checkin", "--goal-id", goal_id, "--occurred-at", day)
        returned = self.run_json(
            GOAL, "checkin", "--goal-id", goal_id, "--occurred-at", "2026-07-20"
        )
        self.assertEqual(
            {item["milestone_type"] for item in returned["new_milestones"]}, {"recovery"}
        )
        listed = self.run_json(GOAL, "milestones", "--goal-id", goal_id)
        recovery = next(item for item in listed["milestones"]
                        if item["milestone_type"] == "recovery")
        self.assertEqual(recovery["evidence"]["gap_days"], 17)

    def test_card_requires_meaning_and_uses_frozen_share_safe_snapshot(self):
        goal = self.create_goal(goal_type="cumulative_count", target=4,
                                total_periods=None, title="完成四次晨间步行")
        goal_id = goal["goal"]["id"]
        self.run_json(GOAL, "checkin", "--goal-id", goal_id, "--occurred-at", "2026-08-01")
        rejected = self.run_json(CARD, "generate", "--goal-id", goal_id, "--format", "html")
        self.assertEqual(rejected["status"], "error")
        self.assertIn("没有值得发卡", rejected["message"])

        for day in ("2026-08-03", "2026-08-05"):
            self.run_json(GOAL, "checkin", "--goal-id", goal_id, "--occurred-at", day)
        milestones = self.run_json(GOAL, "milestones", "--goal-id", goal_id)
        rhythm = next(item for item in milestones["milestones"]
                      if item["milestone_type"] == "rhythm")
        self.run_json(GOAL, "checkin", "--goal-id", goal_id, "--occurred-at", "2026-08-07")
        card = self.run_json(
            CARD, "generate", "--goal-id", goal_id, "--milestone-id", rhythm["id"],
            "--format", "html",
        )
        self.assertEqual(card["status"], "ok")
        self.assertTrue(card["card"]["share_safe"])
        self.assertTrue(card["card"]["snapshot_frozen"])
        self.assertEqual(card["card"]["snapshot_checkin_count"], 3)
        html_text = Path(card["card"]["html_path"]).read_text(encoding="utf-8")
        self.assertIn('data-share-safe="true"', html_text)
        self.assertIn('data-milestone-type="rhythm"', html_text)
        self.assertIn('data-snapshot-checkins="3"', html_text)
        self.assertIn("你找到了第一套可重复的节奏", html_text)
        self.assertNotIn("测试成员", html_text)
        self.assertNotIn("2026-08-01", html_text)
        self.assertNotIn("2026-08-03", html_text)
        self.assertNotIn("2026-08-05", html_text)
        self.assertNotIn("2026-08-07", html_text)

        prefs_path = Path(self.temp.name) / "goal-card-preferences.json"
        prefs_text = prefs_path.read_text(encoding="utf-8")
        self.assertNotIn(self.member_id, prefs_text)
        self.assertNotIn("完成四次晨间步行", prefs_text)
        self.assertNotIn('"target_value"', prefs_text)

    def test_committed_manual_exercise_updates_active_activity_goal(self):
        goal_id = self.create_goal(goal_type="weekly_frequency", target=2)["goal"]["id"]
        exercise = self.run_json(
            EXERCISE, "add", "--member-id", self.member_id, "--exercise-type", "walking",
            "--duration", "30", "--distance-meters", "2500", "--exercise-date", "2026-08-02",
        )
        self.assertEqual(exercise["status"], "ok")
        self.assertEqual(exercise["record"]["distance_meters"], 2500)
        self.assertEqual(len(exercise["goal_updates"]), 1)
        self.assertEqual(exercise["goal_updates"][0]["progress"]["checkin_count"], 1)
        progress = self.run_json(GOAL, "progress", "--goal-id", goal_id, "--as-of", "2026-08-02")
        self.assertEqual(progress["progress"]["current_value"], 1)


if __name__ == "__main__":
    unittest.main()
