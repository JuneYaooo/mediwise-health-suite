import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.story import video
from shared.story.frame import render_ready
from shared.story.normalize import domain_analysis_from_rows


def _story(domain, subject, values, *, delta=1.0, slope_per_day=0.25, claim_allowed=True):
    series = [
        {"date": "2026-07-%02d" % (1 + index * 2), "value": value}
        for index, value in enumerate(values)
    ]
    return {
        "domain": domain,
        "lexicon": {"subject": subject, "unit": "单位"},
        "frame": {
            "shape": "sustained-rise",
            "series": series,
            "coverage": {"recorded_days": len(series), "measurement_count": len(series)},
            "trend": {
                "claim_allowed": claim_allowed,
                "delta": delta,
                "slope_per_day": slope_per_day,
            },
        },
    }


def _png_header(width=1080, height=1440):
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)


class MultiDomainStoryboardTests(unittest.TestCase):
    def test_storyboard_includes_every_recorded_domain_and_individual_domain_scenes(self):
        stories = [
            _story("sleep", "睡眠", [410, 430, 445]),
            _story("vitals", "心率", [70, 72, 74]),
            _story("activity", "步数", [4200, 5100, 6300]),
        ]

        scenes = video.plan_story_scenes(stories, days=14, locale="zh-CN")

        self.assertEqual([scene["role"] for scene in scenes], [
            "cover", "overview", "domain", "domain", "domain", "boundary"
        ])
        self.assertEqual(
            [scene.get("domain") for scene in scenes if scene["role"] == "domain"],
            ["sleep", "vitals", "activity"],
        )
        self.assertIn("3 个维度", scenes[1]["title"])
        self.assertIn("不做跨域相减", scenes[1]["body"])
        self.assertIn("同期不等于因果", str(scenes[-1]["boundaries"]))

    def test_unfitted_story_never_claims_a_robust_fit(self):
        story = _story(
            "sleep", "睡眠", [420], delta=None, slope_per_day=None,
            claim_allowed=True,
        )

        scene = video.plan_story_scenes([story], days=7, locale="zh-CN")[2]

        self.assertEqual(scene["facts"][2][0], "—")
        self.assertEqual(scene["fit_label"], "暂无稳健拟合")
        self.assertNotIn("Theil", scene["fit_label"])

    def test_daily_rate_uses_slope_not_whole_window_delta(self):
        story = _story(
            "sleep", "睡眠", [420, 450, 480], delta=130.0, slope_per_day=10.0
        )

        scene = video.plan_story_scenes([story], days=14, locale="zh-CN")[2]

        self.assertEqual(scene["facts"][2][0], "+10.0单位/天")
        self.assertNotIn("+130.0", scene["facts"][2][0])

    def test_adapter_insufficient_shape_suppresses_an_internal_fit(self):
        story = _story(
            "weight", "体重", [72.0, 71.9, 71.8], delta=-1.3,
            slope_per_day=-0.1, claim_allowed=True,
        )
        story["frame"]["shape"] = "insufficient"

        scene = video.plan_story_scenes([story], days=14, locale="zh-CN")[2]

        self.assertEqual(scene["facts"][2][0], "—")
        self.assertEqual(scene["fit_label"], "记录不足，暂不判断")

    def test_scene_html_is_fixed_size_local_and_preserves_gap_language(self):
        scene = video.plan_story_scenes(
            [_story("sleep", "睡眠", [410, 450])], days=7, locale="zh-CN"
        )[2]

        rendered = video.render_scene_html(scene, locale="zh-CN", index=2)

        self.assertIn("width:1080px;height:1440px", rendered)
        self.assertIn("空白区表示没有记录，不代表数值为零", rendered)
        self.assertIn("window.__ready=true", rendered)
        self.assertNotIn("http://", rendered)
        self.assertNotIn("https://", rendered)


class GenericWeightLoaderTests(unittest.TestCase):
    def test_prefolded_weight_rows_receive_span_gate_fit_and_shape(self):
        rows = [
            {
                "date": "2026-07-%02d" % day,
                "weight": 72.8 - day * 0.1,
                "measurement_count": 1,
            }
            for day in range(1, 8)
        ]

        analysis = domain_analysis_from_rows("weight", rows, 7)
        ready = render_ready("weight", analysis)

        self.assertEqual(analysis["span_days"], 7)
        self.assertEqual(analysis["coverage_ratio"], 1.0)
        self.assertTrue(analysis["trend_claim_allowed"])
        self.assertAlmostEqual(analysis["slope_per_day"], -0.1)
        self.assertEqual(ready["frame"]["shape"], "sustained-fall")
        self.assertEqual(ready["frame"]["trend"]["direction"], "down")

    def test_weight_loader_keeps_fit_private_below_daily_series_gate(self):
        rows = [
            {
                "date": "2026-07-%02d" % day,
                "weight": 72.8 - day * 0.1,
                "measurement_count": 1,
            }
            for day in range(1, 3)
        ]

        analysis = domain_analysis_from_rows("weight", rows, 7)
        ready = render_ready("weight", analysis)

        self.assertFalse(analysis["trend_claim_allowed"])
        self.assertNotIn("trend_delta", analysis)
        self.assertEqual(ready["frame"]["shape"], "insufficient")
        self.assertIsNone(ready["frame"]["trend"].get("delta"))


class VideoPackageTests(unittest.TestCase):
    def test_every_scene_gets_a_scene_aware_camera_move(self):
        scenes = video.plan_story_scenes(
            [
                _story("sleep", "睡眠", [410, 430, 445]),
                _story("activity", "步数", [4200, 5100, 6300]),
            ],
            days=7,
            locale="zh-CN",
        )
        paths = [Path("%02d.png" % index) for index in range(len(scenes))]

        command, _duration = video._video_command(
            "ffmpeg", paths, scenes, Path("health_story.mp4")
        )
        filters = command[command.index("-filter_complex") + 1]

        self.assertEqual(filters.count("zoompan="), len(scenes))
        self.assertIn("1.000+0.034", filters)
        self.assertIn("1.034-0.022", filters)
        self.assertIn("0.70-0.34", filters)
        self.assertIn("0.28+0.34", filters)

    def test_package_has_mp4_individual_pngs_and_manifests(self):
        stories = [
            _story("sleep", "睡眠", [410, 430, 445]),
            _story("activity", "步数", [4200, 5100, 6300]),
        ]

        def fake_capture(_source, output, **_kwargs):
            Path(output).write_bytes(_png_header())
            return {
                "status": "ok", "image_path": output, "width": 1080,
                "height": 1440, "file_size": Path(output).stat().st_size,
                "capture": "test", "waited_for_ready": True,
            }

        def fake_run(command, **_kwargs):
            class Result:
                returncode = 0
                stderr = ""
                stdout = ""

            result = Result()
            if command[0] == "ffprobe-test":
                result.stdout = json.dumps({
                    "streams": [{
                        "index": 0, "codec_name": "h264", "codec_type": "video",
                        "width": 1080, "height": 1920, "pix_fmt": "yuv420p",
                        "r_frame_rate": "30/1",
                    }],
                    "format": {"duration": "15.400", "size": "4096"},
                })
            elif "-filter_complex" in command:
                Path(command[-1]).write_bytes(b"fake mp4")
            elif "-vf" in command:
                Path(command[-1]).write_bytes(_png_header(960, 640))
            return result

        with tempfile.TemporaryDirectory() as tmpdir:
            stale_frames = Path(tmpdir) / "public" / "frames"
            stale_frames.mkdir(parents=True)
            (stale_frames / "99-obsolete.png").write_bytes(_png_header())
            with patch.object(video.subprocess, "run", side_effect=fake_run):
                result = video.render_health_story_video(
                    stories,
                    tmpdir,
                    days=7,
                    locale="zh-CN",
                    capture=fake_capture,
                    ffmpeg_binary="ffmpeg-test",
                    ffprobe_binary="ffprobe-test",
                )

            self.assertEqual(result["status"], "ok")
            self.assertTrue(Path(result["mp4_path"]).is_file())
            self.assertEqual(len(result["scene_images"]), 5)
            self.assertTrue(all(Path(item["png_path"]).is_file() for item in result["scene_images"]))
            self.assertEqual(result["audio_strategy"], "silent")
            self.assertEqual(result["motion_strategy"], video.MOTION_STRATEGY)
            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["domains"], ["sleep", "activity"])
            self.assertEqual(len(manifest["scene_images"]), 5)
            self.assertEqual(manifest["motion_strategy"], video.MOTION_STRATEGY)
            self.assertFalse((stale_frames / "99-obsolete.png").exists())
            public_names = sorted(path.name for path in (Path(tmpdir) / "public").iterdir())
            self.assertEqual(public_names, ["cover.png", "frames", "health_story.mp4"])


if __name__ == "__main__":
    unittest.main()
