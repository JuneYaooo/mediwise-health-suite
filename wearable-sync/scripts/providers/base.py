"""Base provider abstract class for wearable device data sync."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RawMetric:
    """Raw metric data from a wearable device before normalization."""
    metric_type: str          # Provider-specific type (e.g. "HEART_RATE", "huawei.heartRate")
    value: str                # Raw value (number or JSON string)
    timestamp: str            # ISO datetime string
    extra: dict = field(default_factory=dict)  # Provider-specific extra data


class BaseProvider(ABC):
    """Abstract base class for wearable device data providers.

    Each provider implements device-specific logic for authentication,
    data fetching, and supported metric enumeration.
    """

    provider_name: str = "base"

    @abstractmethod
    def authenticate(self, config: dict) -> bool:
        """Validate and authenticate with the given config.

        For OAuth providers: validates tokens are present and not expired.
        For local providers (Gadgetbridge): validates file path exists.

        Args:
            config: Provider-specific configuration dict.

        Returns:
            True if authentication is valid.
        """
        ...

    @abstractmethod
    def fetch_metrics(self, device_id: str, start_time: Optional[str] = None,
                      end_time: Optional[str] = None) -> list[RawMetric]:
        """Fetch raw metrics from the device/source.

        Args:
            device_id: The wearable device record ID.
            start_time: ISO datetime string for range start (inclusive). None = from last sync.
            end_time: ISO datetime string for range end (inclusive). None = now.

        Returns:
            List of RawMetric objects.
        """
        ...

    @abstractmethod
    def get_supported_metrics(self) -> list[str]:
        """Return list of metric types this provider can supply.

        Returns normalized metric type names (e.g. "heart_rate", "steps", "sleep", "blood_oxygen").
        """
        ...

    @abstractmethod
    def test_connection(self, config: dict) -> bool:
        """Test if the provider connection/config is working.

        Args:
            config: Provider-specific configuration dict.

        Returns:
            True if connection test passes.
        """
        ...
