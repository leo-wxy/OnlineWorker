from core.usage.contracts import UsagePluginDescriptor
from plugins.usage.builtin.ccusage.python.runtime import runtime_identity, run_ccusage_summary


def create_usage_plugin_descriptor() -> UsagePluginDescriptor:
    return UsagePluginDescriptor(
        plugin_id="ccusage",
        runtime_identity=runtime_identity,
        get_summary=run_ccusage_summary,
    )
