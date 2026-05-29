from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AiServiceConfig:
    id: str
    name: str = ""
    protocol: str = "openai_compatible_chat"
    base_url: str = ""
    endpoint: str = ""
    api_key: str = ""
    api_key_env: str = ""
    models: tuple[str, ...] = ()
    default_model: str = ""
    timeout_seconds: int = 20
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", str(self.id or "").strip())
        object.__setattr__(self, "name", str(self.name or self.id).strip())
        object.__setattr__(self, "protocol", str(self.protocol or "openai_compatible_chat").strip())
        object.__setattr__(self, "base_url", str(self.base_url or "").strip().rstrip("/"))
        object.__setattr__(self, "endpoint", str(self.endpoint or "").strip())
        object.__setattr__(self, "api_key", str(self.api_key or "").strip())
        object.__setattr__(self, "api_key_env", str(self.api_key_env or "").strip())
        models = tuple(str(model or "").strip() for model in self.models if str(model or "").strip())
        object.__setattr__(self, "models", models)
        default_model = str(self.default_model or "").strip()
        object.__setattr__(self, "default_model", default_model or (models[0] if models else ""))
        object.__setattr__(self, "timeout_seconds", max(1, int(self.timeout_seconds or 20)))
        object.__setattr__(self, "enabled", bool(self.enabled))


@dataclass(frozen=True)
class AiScenarioConfig:
    id: str
    enabled: bool = False
    service_id: str = ""
    model: str = ""
    output_schema: str = "text"
    fallback: str = ""
    limits: dict[str, int] = field(default_factory=dict)
    prompt_template: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", str(self.id or "").strip())
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "service_id", str(self.service_id or "").strip())
        object.__setattr__(self, "model", str(self.model or "").strip())
        object.__setattr__(self, "output_schema", str(self.output_schema or "text").strip())
        object.__setattr__(self, "fallback", str(self.fallback or "").strip())
        normalized_limits: dict[str, int] = {}
        for key, value in (self.limits or {}).items():
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                normalized_limits[str(key)] = parsed
        object.__setattr__(self, "limits", normalized_limits)
        object.__setattr__(self, "prompt_template", str(self.prompt_template or ""))


@dataclass(frozen=True)
class AiConfig:
    services: dict[str, AiServiceConfig] = field(default_factory=dict)
    scenarios: dict[str, AiScenarioConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class AiScenarioResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    fallback: str = ""
    error: str = ""
