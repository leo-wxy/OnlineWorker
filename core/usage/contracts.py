from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class UsageSummaryRequest:
    plugin_id: str
    source_id: str
    start_date: str
    end_date: str
    timezone: str = "local"


@dataclass(frozen=True)
class UsagePluginDescriptor:
    plugin_id: str
    runtime_identity: Callable[[], str]
    get_summary: Callable[[UsageSummaryRequest], dict]
