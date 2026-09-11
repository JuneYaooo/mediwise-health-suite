"""未解析营养不得被写成 0，也不得被当成 0 参与汇总。

`add-meal` 曾经在没有任何食物数据源时返回 `status: ok`、消息 `共0.0kcal`，
并把 `total_calories = 0.0` 落库。危险之处不在于难看，而在于 0 会被下游
读成"真实摄入"：`calorie_balance` 把它算作一个已记录的摄入日计入平均值
分母，`daily_summary` 还会据此编造出三大营养素比例。

同一前提下**读取**路径一直是诚实的（`food-lookup` 返回 `unavailable`）。
所以这一组测试的核心断言是**两条路径给出一致的说法**：写进去的是未知，
读出来也必须是未知。

NULL = 未知（未解析），0 = 确认是零（如水、黑咖啡）。两者不可互换。
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIET_SCRIPTS = ROOT / "diet-tracker" / "scripts"
WEIGHT_SCRIPTS = ROOT / "weight-manager" / "scripts"
# `health_db` 住在 tracker 里，模块靠 path_setup 找它；测试直接 import 就要自己挂。
HEALTH_SCRIPTS = ROOT / "mediwise-health-tracker" / "scripts"
for _p in (DIET_SCRIPTS, WEIGHT_SCRIPTS, HEALTH_SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# 这些环境变量一旦存在，"未配置任何数据源"的前提就不成立，
# 而整个测试类的意义正建立在该前提上。
SOURCE_ENV_VARS = ("USDA_API_KEY", "OPENFOODFACTS_ENABLED", "MEDIWISE_USDA_API_KEY")


class UnresolvedNutritionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["MEDIWISE_DATA_DIR"] = self.tmpdir.name
        os.environ["MEDIWISE_SINGLE_USER"] = "1"
        self._saved_env = {k: os.environ.pop(k, None) for k in SOURCE_ENV_VARS}

        # `config.DATA_DIR` 在 import 时就固化了，必须先重载它，
        # 否则每个用例都会写进第一个临时目录（并撞上 members.id 唯一约束）。
        importlib.reload(importlib.import_module("config"))
        self.health_db = importlib.reload(importlib.import_module("health_db"))
        self.food_lookup = importlib.reload(importlib.import_module("food_lookup"))
        self.diet = importlib.reload(importlib.import_module("diet"))
        self.nutrition_goal = importlib.reload(importlib.import_module("nutrition_goal"))

        self.health_db.ensure_db()
        self.member_id = "mem_diet_nutrition"
        now = self.health_db.now_iso()
        with self.health_db.transaction() as conn:
            conn.execute(
                """INSERT INTO members (id, name, relation, owner_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (self.member_id, "测试成员", "本人", "owner_test", now, now),
            )
            conn.commit()

    def tearDown(self):
        for key, value in self._saved_env.items():
            if value is not None:
                os.environ[key] = value
        os.environ.pop("MEDIWISE_DATA_DIR", None)
        os.environ.pop("MEDIWISE_SINGLE_USER", None)
        self.tmpdir.cleanup()

    # ---- helpers -----------------------------------------------------------

    def _capture_json(self, func, *args, **kwargs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            func(*args, **kwargs)
        output = buf.getvalue().strip()
        self.assertTrue(output, f"No JSON output from {func.__name__}")
        return json.loads(output)

    def _add_meal(self, items, meal_date="2026-09-11", meal_type="lunch"):
        return self._capture_json(
            self.diet.add_meal,
            argparse.Namespace(
                member_id=self.member_id, meal_type=meal_type, meal_date=meal_date,
                meal_time=None, items=json.dumps(items, ensure_ascii=False),
                note=None, owner_id=None,
            ),
        )

    def _add_item(self, record_id, **overrides):
        params = dict(
            record_id=record_id, food_name="水", amount=None, unit=None,
            calories=None, protein=None, fat=None, carbs=None, fiber=None,
            note=None, owner_id=None,
        )
        params.update(overrides)
        return self._capture_json(self.diet.add_item, argparse.Namespace(**params))

    def _item_rows(self, record_id):
        conn = self.health_db.get_lifestyle_connection()
        try:
            return self.health_db.rows_to_list(conn.execute(
                "SELECT * FROM diet_items WHERE record_id=? AND is_deleted=0", (record_id,)
            ).fetchall())
        finally:
            conn.close()

    def _record_row(self, record_id):
        conn = self.health_db.get_lifestyle_connection()
        try:
            return self.health_db.row_to_dict(conn.execute(
                "SELECT * FROM diet_records WHERE id=?", (record_id,)
            ).fetchone())
        finally:
            conn.close()

    # ---- the write path must not invent zero --------------------------------

    def test_an_unresolvable_meal_stores_null_and_says_so(self):
        """无数据源时：五个营养列与记录级合计全为 NULL，消息不出现 0 卡。"""
        result = self._add_meal([{"food_name": "红烧肉", "amount": 200, "unit": "g"},
                                 {"food_name": "米饭", "amount": 150, "unit": "g"}])

        self.assertEqual(result["status"], "ok")
        record_id = result["record"]["id"]

        for row in self._item_rows(record_id):
            for field in ("calories", "protein", "fat", "carbs", "fiber"):
                self.assertIsNone(row[field], f"{row['food_name']}.{field} must be NULL, not 0")
            self.assertIn("[未解析营养]", row["note"])

        record = self._record_row(record_id)
        for field in ("total_calories", "total_protein", "total_fat", "total_carbs", "total_fiber"):
            self.assertIsNone(record[field], f"{field} must be NULL, not 0")

        self.assertNotRegex(result["message"], r"0(\.0)?\s*kcal")
        self.assertEqual(result["nutrition_status"], "unresolved")
        self.assertEqual(len(result["unresolved_items"]), 2)
        self.assertIn("action_required", result)

    def test_the_read_path_tells_the_same_story_as_the_write_path(self):
        """这一条才是当初能拦住该缺陷的断言。

        写入路径说"已记录"，读取路径说"不可用"——同一份食物、同一个前提，
        两条路径的说法必须一致，否则用户看到的失败完全取决于他问了哪个动作。
        """
        self._add_meal([{"food_name": "红烧肉", "amount": 200, "unit": "g"}])

        found = self.food_lookup.search("红烧肉", limit=1, source="auto")
        self.assertEqual(found["status"], "unavailable")

        looked_up = self.food_lookup.lookup("红烧肉")
        self.assertEqual(looked_up["status"], "unavailable")

    def test_a_mixed_meal_reports_unknown_rather_than_a_partial_sum(self):
        """300 已知 + 未知，合计必须是 NULL。

        报成 300 会被读成一个真实的 300 kcal 摄入，比"未知"更危险——
        未知至少会让人去问，而一个偏低的数字不会。
        """
        result = self._add_meal([
            {"food_name": "鸡胸肉", "calories": 300, "protein": 40},
            {"food_name": "红烧肉", "amount": 200, "unit": "g"},
        ])

        record = self._record_row(result["record"]["id"])
        self.assertIsNone(record["total_calories"])
        self.assertIsNone(record["total_protein"])
        self.assertEqual(result["nutrition_status"], "partial")
        self.assertIn("已知部分合计 300kcal", result["message"])
        self.assertNotRegex(result["message"], r"共\s*300(\.0)?\s*kcal")

    def test_an_explicit_zero_is_an_assertion_and_is_never_queried(self):
        """显式 0 是用户/Agent 的断言（如水），必须原样存 0 且不触发查询。

        旧代码 `if item.get('calories')` 把 0 当成"没给"，
        于是"我喝的是水，0 卡"会被丢弃并被一次查询覆盖。
        """
        from unittest import mock

        with mock.patch.object(self.food_lookup, "lookup") as lookup:
            result = self._add_meal([{"food_name": "水", "amount": 250,
                                      "unit": "ml", "calories": 0}])
            lookup.assert_not_called()

        record_id = result["record"]["id"]
        row = self._item_rows(record_id)[0]
        self.assertEqual(row["calories"], 0)
        self.assertIsNone(row["protein"], "未给出的字段必须为 NULL，不能补 0")
        self.assertNotIn("[未解析营养]", row["note"] or "")
        self.assertEqual(result["nutrition_status"], "resolved")

    def test_an_omitted_key_and_an_explicit_null_behave_the_same(self):
        """省略 key 与显式 null 都是"未知"——两种写法不能一个查一个不查。"""
        omitted = self._add_meal([{"food_name": "红烧肉"}], meal_date="2026-09-12")
        explicit = self._add_meal(
            [{"food_name": "红烧肉", "calories": None, "protein": None}],
            meal_date="2026-09-13",
        )

        for result in (omitted, explicit):
            record = self._record_row(result["record"]["id"])
            self.assertIsNone(record["total_calories"])
            self.assertEqual(result["nutrition_status"], "unresolved")

    def test_add_item_without_calories_stores_null_and_flags_the_record(self):
        meal = self._add_meal([{"food_name": "米饭", "calories": 250, "protein": 5}],
                              meal_date="2026-09-14")
        record_id = meal["record"]["id"]

        result = self._add_item(record_id, food_name="红烧肉", amount=200, unit="g")

        row = [r for r in self._item_rows(record_id) if r["food_name"] == "红烧肉"][0]
        self.assertIsNone(row["calories"])
        record = self._record_row(record_id)
        self.assertIsNone(record["total_calories"])
        self.assertEqual(result["nutrition_status"], "partial")
        self.assertNotRegex(result["message"], r"0(\.0)?\s*kcal")

    def test_add_item_with_explicit_zero_calories_is_recorded_as_zero(self):
        meal = self._add_meal([{"food_name": "米饭", "calories": 250, "protein": 5}],
                              meal_date="2026-09-15")
        record_id = meal["record"]["id"]

        result = self._add_item(record_id, food_name="水", amount=250, unit="ml", calories=0)

        row = [r for r in self._item_rows(record_id) if r["food_name"] == "水"][0]
        self.assertEqual(row["calories"], 0)
        self.assertEqual(self._record_row(record_id)["total_calories"], 250)
        self.assertEqual(result["nutrition_status"], "resolved")

    def test_deleting_the_unresolved_item_makes_the_record_known_again(self):
        """`_compute_totals` 也在删除路径上跑，所以未知应当自动消失。"""
        meal = self._add_meal([
            {"food_name": "鸡胸肉", "calories": 300},
            {"food_name": "红烧肉", "amount": 200, "unit": "g"},
        ], meal_date="2026-09-16")
        record_id = meal["record"]["id"]
        self.assertIsNone(self._record_row(record_id)["total_calories"])

        unknown = [r for r in self._item_rows(record_id) if r["calories"] is None][0]
        self._capture_json(self.diet.delete_record,
                           argparse.Namespace(id=unknown["id"], type="item", owner_id=None))

        self.assertEqual(self._record_row(record_id)["total_calories"], 300)

    def test_a_source_hit_without_calories_is_not_reported_as_resolved(self):
        """来源命中但缺热量：不能打 [自动填充]，也不能写 0。

        旧 `_val` 在来源缺字段时返回 0 却仍打上 [自动填充] 标记，
        等于把"来源里没有"伪装成"来源说是 0"。
        """
        from unittest import mock

        stub = {"status": "ok", "query": "谜之食物",
                "result": {"name": "谜之食物", "kcal": None, "protein": None,
                           "fat": None, "carbs": None, "fiber": None,
                           "source": "cfcd", "source_name": "测试数据包"},
                "source": "cfcd"}
        with mock.patch.object(self.food_lookup, "lookup", return_value=stub):
            result = self._add_meal([{"food_name": "谜之食物"}], meal_date="2026-09-17")

        row = self._item_rows(result["record"]["id"])[0]
        self.assertIsNone(row["calories"], "来源缺字段时必须存 NULL，不能存 0")
        self.assertNotIn("[自动填充]", row["note"] or "")
        self.assertIn("[未解析营养]", row["note"])
        self.assertEqual(result["unresolved_items"][0]["reason"], "source_missing_field")

    # ---- the read path must not launder unknown into zero -------------------

    def test_daily_summary_refuses_to_build_a_ratio_from_unknown(self):
        self._add_meal([{"food_name": "红烧肉", "amount": 200, "unit": "g"}],
                       meal_date="2026-09-18")

        result = self._capture_json(
            self.diet.daily_summary,
            argparse.Namespace(member_id=self.member_id, date="2026-09-18", owner_id=None),
        )

        for field in ("calories", "protein", "fat", "carbs", "fiber"):
            self.assertIsNone(result["totals"][field], f"totals.{field} must be NULL")
        self.assertEqual(result["macro_ratio"], {}, "不得由未知编造三大营养素比例")
        self.assertEqual(result["unresolved_records"], 1)
        self.assertIsNone(result["meals"][0]["calories"])

    def test_a_day_with_no_records_still_totals_zero(self):
        """没记录与记了但未解析是两回事，前者由 meal_count 表达。"""
        result = self._capture_json(
            self.diet.daily_summary,
            argparse.Namespace(member_id=self.member_id, date="2026-01-01", owner_id=None),
        )
        self.assertEqual(result["meal_count"], 0)
        self.assertEqual(result["totals"]["calories"], 0)
        self.assertEqual(result["unresolved_records"], 0)

    def test_goal_comparison_does_not_claim_an_unresolved_day_is_off_target(self):
        """未解析日既非达标也非未达标——旧代码会产出"记录值为目标的 0.0%"。"""
        self._capture_json(
            self.nutrition_goal.cmd_set,
            argparse.Namespace(member_id=self.member_id, calories=1800, protein=None,
                               fat=None, carbs=None, fiber=None, note=None),
        )
        self._add_meal([{"food_name": "红烧肉", "amount": 200, "unit": "g"}],
                       meal_date="2026-09-19")

        result = self._capture_json(
            self.nutrition_goal.cmd_daily,
            argparse.Namespace(member_id=self.member_id, date="2026-09-19"),
        )

        self.assertEqual(result["comparison"], {})
        self.assertEqual(result["issues"], [])
        self.assertIsNone(result["on_track"], "未知不下达标结论")
        for field in ("calories", "protein", "fat", "carbs", "fiber"):
            self.assertIsNone(result["intake"][field])
        self.assertTrue(result["intake"]["has_records"])
        self.assertTrue(result["intake"]["unresolved"])

    def test_a_day_with_no_records_is_not_declared_on_track(self):
        """没有记录同样不可判断——"什么都没记"不等于"达标"。"""
        self._capture_json(
            self.nutrition_goal.cmd_set,
            argparse.Namespace(member_id=self.member_id, calories=1800, protein=None,
                               fat=None, carbs=None, fiber=None, note=None),
        )
        result = self._capture_json(
            self.nutrition_goal.cmd_daily,
            argparse.Namespace(member_id=self.member_id, date="2026-01-01"),
        )
        self.assertFalse(result["intake"]["has_records"])
        self.assertIsNone(result["on_track"])

    def test_calorie_balance_keeps_unresolved_days_out_of_the_divisor(self):
        """影响最大的一处：0 卡日被算作"已记录摄入日"会直接污染热量收支。"""
        weight_analysis = importlib.reload(importlib.import_module("weight_analysis"))
        self._add_meal([{"food_name": "鸡胸肉", "calories": 300}], meal_date="2026-09-09")
        self._add_meal([{"food_name": "红烧肉", "amount": 200, "unit": "g"}],
                       meal_date="2026-09-10")

        result = self._capture_json(
            weight_analysis.calorie_balance,
            argparse.Namespace(member_id=self.member_id, days=7,
                               owner_id=None, as_of=None),
        )

        self.assertEqual(result["intake_record_days"], 2)
        self.assertEqual(result["intake_resolved_days"], 1)
        self.assertEqual(result["intake_unresolved_days"], 1)
        # 300/1，而不是 300/2 也不是 (300+0)/2
        self.assertEqual(result["average_intake_on_recorded_days"], 300.0)

    def test_weekly_summary_averages_only_resolved_days(self):
        nutrition = importlib.reload(importlib.import_module("nutrition"))
        self._add_meal([{"food_name": "鸡胸肉", "calories": 300}], meal_date="2026-09-09")
        self._add_meal([{"food_name": "红烧肉", "amount": 200, "unit": "g"}],
                       meal_date="2026-09-10")

        result = self._capture_json(
            nutrition.weekly_summary,
            argparse.Namespace(member_id=self.member_id, end_date="2026-09-11", owner_id=None),
        )

        self.assertEqual(result["days_with_data"], 2)
        self.assertEqual(result["unresolved_days"], 1)
        self.assertEqual(result["days_averaged"]["calories"], 1)
        self.assertEqual(result["average"]["calories"], 300.0)


if __name__ == "__main__":
    unittest.main()
