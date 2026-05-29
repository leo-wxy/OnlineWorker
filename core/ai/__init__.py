from .config import load_ai_config
from .contracts import AiConfig, AiScenarioConfig, AiScenarioResult, AiServiceConfig

__all__ = [
    "AiConfig",
    "AiScenarioConfig",
    "AiScenarioResult",
    "AiServiceConfig",
    "load_ai_config",
    "run_ai_scenario",
]


def __getattr__(name: str):
    if name == "run_ai_scenario":
        from .scenarios import run_ai_scenario

        return run_ai_scenario
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
