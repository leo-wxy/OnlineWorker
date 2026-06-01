import { startTransition, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useDashboardState } from "../hooks";
import { useI18n } from "../i18n";
import {
  DashboardAlerts,
  DashboardError,
  DashboardHero,
  DashboardSidebar,
  ProviderStatusList,
  getOverallStyles,
  type ServiceAction,
} from "../components/dashboard";
import type { ProviderDashboardStatus } from "../types";

interface Props {
  onOpenLogs: () => void;
  onOpenSetup: () => void;
  onOpenSessions: () => void;
}

export function Dashboard({ onOpenLogs, onOpenSetup, onOpenSessions }: Props) {
  const { t } = useI18n();
  const {
    dashboardState,
    loading,
    error,
    refresh,
    providers,
    serviceControlStatus,
    canOpenCodexTuiHost,
  } = useDashboardState();
  const [savingProviderId, setSavingProviderId] = useState<string | null>(null);
  const [serviceAction, setServiceAction] = useState<ServiceAction | null>(null);

  const overall = getOverallStyles(t)[dashboardState?.overall ?? "unknown"];
  const controlStatus = serviceControlStatus;
  const serviceBusy = serviceAction !== null;

  const handleProviderFlagsChange = async (
    provider: ProviderDashboardStatus,
    nextManaged: boolean,
    nextAutostart: boolean
  ) => {
    setSavingProviderId(provider.id);
    try {
      await invoke("set_provider_flags", {
        providerId: provider.id,
        managed: nextManaged,
        autostart: nextManaged && nextAutostart,
      });
      if (controlStatus?.running) {
        await invoke("service_restart");
      }
      window.setTimeout(() => {
        startTransition(() => {
          void refresh();
        });
      }, controlStatus?.running ? 1200 : 200);
    } catch (err) {
      console.error("Provider flag update error:", err);
      alert(String(err));
    } finally {
      setSavingProviderId(null);
    }
  };

  const handleServiceAction = async (nextAction: ServiceAction) => {
    setServiceAction(nextAction);
    try {
      if (nextAction === "restart") {
        await invoke("service_restart");
      } else if (nextAction === "stop") {
        await invoke("service_stop");
      } else {
        await invoke("service_start");
      }
      window.setTimeout(() => void refresh(), 800);
    } catch (err) {
      console.error("Service action error:", err);
      alert(String(err));
    } finally {
      setServiceAction(null);
    }
  };

  const handleOpenCodexTuiHost = async () => {
    const activity = dashboardState?.recentActivity;
    const workspacePath = activity?.activeWorkspacePath?.trim();
    const threadId = activity?.activeSessionId?.trim();
    if (!workspacePath || !threadId) {
      return;
    }
    try {
      await invoke("open_codex_tui_host_terminal", {
        workspacePath,
        threadId,
      });
    } catch (err) {
      console.error("Open codex TUI host terminal error:", err);
      alert(String(err));
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <DashboardHero
        dashboardState={dashboardState}
        loading={loading}
        overall={overall}
        serviceAction={serviceAction}
        serviceBusy={serviceBusy}
        controlStatus={controlStatus}
        texts={t}
        onOpenLogs={onOpenLogs}
        onServiceAction={(action) => void handleServiceAction(action)}
      />

      <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-6">
          <DashboardSidebar
            dashboardState={dashboardState}
            canOpenCodexTuiHost={canOpenCodexTuiHost}
            texts={t}
            onOpenCodexTuiHost={() => void handleOpenCodexTuiHost()}
            onOpenLogs={onOpenLogs}
            onOpenSetup={onOpenSetup}
            onOpenSessions={onOpenSessions}
          />

          <DashboardAlerts
            alerts={dashboardState?.alerts ?? []}
            texts={t}
            onOpenLogs={onOpenLogs}
            onOpenSetup={onOpenSetup}
          />

          <DashboardError error={error} texts={t} />
        </div>

        <ProviderStatusList
          loading={loading}
          providers={providers}
          savingProviderId={savingProviderId}
          texts={t}
          onProviderFlagsChange={(provider, nextManaged, nextAutostart) => {
            void handleProviderFlagsChange(provider, nextManaged, nextAutostart);
          }}
          onRefresh={() => void refresh()}
        />
      </div>
    </div>
  );
}
