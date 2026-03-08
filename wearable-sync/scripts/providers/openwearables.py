"""OpenWearables provider - unified API (STUB).

NOTE: OpenWearables currently does not support Huawei or Xiaomi devices.
Planned for Phase 3.
"""

from __future__ import annotations

from .base import BaseProvider, RawMetric


class OpenWearablesProvider(BaseProvider):
    """Provider for OpenWearables unified API (not yet implemented)."""

    provider_name = "openwearables"

    def authenticate(self, config: dict) -> bool:
        raise NotImplementedError(
            "OpenWearables Provider 尚未实现。"
            "该平台目前不支持华为/小米设备。"
            "计划在第三阶段接入。"
        )

    def fetch_metrics(self, device_id: str, start_time: str = None,
                      end_time: str = None) -> list[RawMetric]:
        raise NotImplementedError("OpenWearables Provider 尚未实现（第三阶段）")

    def get_supported_metrics(self) -> list[str]:
        return ["heart_rate", "blood_oxygen", "sleep", "steps"]

    def test_connection(self, config: dict) -> bool:
        raise NotImplementedError("OpenWearables Provider 尚未实现（第三阶段）")
