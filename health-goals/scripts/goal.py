"""CLI wrapper for the shared user-confirmed health goal engine."""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
from path_setup import setup_mediwise_path

setup_mediwise_path()

from goal_engine import (
    create_goal,
    evaluate_goal,
    get_goal,
    list_goals,
    list_milestones,
    record_checkin,
    set_goal_status,
)
from health_db import output_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MediWise 健康目标与打卡")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--member-id", required=True)
    create.add_argument("--domain", required=True)
    create.add_argument("--goal-type", required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--target-value", required=True, type=float)
    create.add_argument("--total-periods", type=int)
    create.add_argument("--start-date")
    create.add_argument("--end-date")
    create.add_argument("--week-start", type=int, default=0)
    create.add_argument("--source", default="user_defined")
    create.add_argument("--rules-json", default="{}")
    create.add_argument("--confirmed", action="store_true")
    create.add_argument("--owner-id")

    listing = sub.add_parser("list")
    listing.add_argument("--member-id", required=True)
    listing.add_argument("--include-inactive", action="store_true")
    listing.add_argument("--owner-id")

    view = sub.add_parser("view")
    view.add_argument("--goal-id", required=True)
    view.add_argument("--owner-id")

    checkin = sub.add_parser("checkin")
    checkin.add_argument("--goal-id", required=True)
    checkin.add_argument("--occurred-at")
    checkin.add_argument("--value", type=float)
    checkin.add_argument("--duration-minutes", type=float)
    checkin.add_argument("--source", default="manual")
    checkin.add_argument("--source-record-type")
    checkin.add_argument("--source-record-id")
    checkin.add_argument("--note")
    checkin.add_argument("--owner-id")

    progress = sub.add_parser("progress")
    progress.add_argument("--goal-id", required=True)
    progress.add_argument("--as-of")
    progress.add_argument("--owner-id")

    status = sub.add_parser("status")
    status.add_argument("--goal-id", required=True)
    status.add_argument("--status", required=True)
    status.add_argument("--owner-id")

    milestones = sub.add_parser("milestones")
    milestones.add_argument("--goal-id", required=True)
    milestones.add_argument("--unclaimed-only", action="store_true")
    milestones.add_argument("--owner-id")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "create":
        try:
            rules = json.loads(args.rules_json or "{}")
        except json.JSONDecodeError:
            output_json({"status": "error", "message": "rules_json 必须是 JSON 对象"})
            return
        if not isinstance(rules, dict):
            output_json({"status": "error", "message": "rules_json 必须是 JSON 对象"})
            return
        result = create_goal(
            args.member_id,
            domain=args.domain,
            goal_type=args.goal_type,
            title=args.title,
            target_value=args.target_value,
            confirmed=args.confirmed,
            owner_id=args.owner_id,
            total_periods=args.total_periods,
            start_date=args.start_date,
            end_date=args.end_date,
            week_start=args.week_start,
            source=args.source,
            rules=rules,
        )
    elif args.command == "list":
        result = list_goals(args.member_id, args.owner_id, args.include_inactive)
    elif args.command == "view":
        goal = get_goal(args.goal_id, args.owner_id)
        result = (
            {"status": "ok", "goal": goal, "progress": evaluate_goal(args.goal_id, owner_id=args.owner_id).get("progress")}
            if goal else {"status": "error", "message": "未找到目标或无权访问"}
        )
    elif args.command == "checkin":
        result = record_checkin(
            args.goal_id,
            occurred_at=args.occurred_at,
            value=args.value,
            duration_minutes=args.duration_minutes,
            source=args.source,
            source_record_type=args.source_record_type,
            source_record_id=args.source_record_id,
            note=args.note,
            owner_id=args.owner_id,
        )
    elif args.command == "progress":
        result = evaluate_goal(args.goal_id, owner_id=args.owner_id, as_of=args.as_of)
    elif args.command == "status":
        result = set_goal_status(args.goal_id, args.status, args.owner_id)
    else:
        result = list_milestones(args.goal_id, args.owner_id, args.unclaimed_only)
    output_json(result)


if __name__ == "__main__":
    main()

