import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { CommandRegistryResponse } from "../types";

interface UseCommandRegistryReturn {
  registry: CommandRegistryResponse | null;
  loading: boolean;
  refreshing: boolean;
  publishing: boolean;
  updatingCommandId: string | null;
  error: string | null;
  refresh: () => Promise<void>;
  setTelegramEnabled: (commandId: string, enabled: boolean) => Promise<void>;
  publish: () => Promise<void>;
}

export function useCommandRegistry(): UseCommandRegistryReturn {
  const [registry, setRegistry] = useState<CommandRegistryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [updatingCommandId, setUpdatingCommandId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const next = await invoke<CommandRegistryResponse>("get_command_registry");
      setRegistry(next);
      setError(null);
    } catch (loadError) {
      setError(String(loadError));
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const next = await invoke<CommandRegistryResponse>("refresh_command_registry");
      setRegistry(next);
      setError(null);
    } catch (refreshError) {
      setError(String(refreshError));
    } finally {
      setRefreshing(false);
      setLoading(false);
    }
  }, []);

  const setTelegramEnabled = useCallback(async (commandId: string, enabled: boolean) => {
    setUpdatingCommandId(commandId);
    try {
      const next = await invoke<CommandRegistryResponse>("set_command_telegram_enabled", {
        commandId,
        enabled,
      });
      setRegistry(next);
      setError(null);
    } catch (updateError) {
      setError(String(updateError));
      throw updateError;
    } finally {
      setUpdatingCommandId(null);
    }
  }, []);

  const publish = useCallback(async () => {
    setPublishing(true);
    try {
      const next = await invoke<CommandRegistryResponse>("publish_telegram_commands");
      setRegistry(next);
      setError(null);
    } catch (publishError) {
      setError(String(publishError));
      throw publishError;
    } finally {
      setPublishing(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return {
    registry,
    loading,
    refreshing,
    publishing,
    updatingCommandId,
    error,
    refresh,
    setTelegramEnabled,
    publish,
  };
}
