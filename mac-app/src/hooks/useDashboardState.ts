import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { DashboardState } from "../types";

interface UseDashboardStateReturn {
  dashboardState: DashboardState | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useDashboardState(): UseDashboardStateReturn {
  const [dashboardState, setDashboardState] = useState<DashboardState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await invoke<DashboardState>("get_dashboard_state");
      setDashboardState(next);
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return { dashboardState, loading, error, refresh };
}
