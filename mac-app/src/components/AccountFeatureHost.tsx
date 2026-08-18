import { Component, useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react";
import { invoke as tauriInvoke } from "@tauri-apps/api/core";


export interface AccountFeatureDescriptor {
  feature_id: string;
  label: string;
  frontend_entry: string;
  backend_entry: string;
}

export interface CapabilityHandle {
  handleId: string;
  displayName: string;
  expiresAt: number;
}

export interface LoopbackHandle {
  handleId: string;
  redirectUri: string;
  expiresAt: number;
}

export interface LoopbackResult {
  status: string;
  callbackUrl?: string;
}

export interface AccountFeatureApi {
  invoke: (action: string, payload?: Record<string, unknown>, handles?: Array<{ handleId: string; mode: "open" | "save" }>) => Promise<Record<string, unknown>>;
  chooseOpen: () => Promise<CapabilityHandle | null>;
  chooseSave: (suggestedName: string) => Promise<CapabilityHandle | null>;
  openBrowser: (url: string) => Promise<void>;
  beginLoopback: (preferredPort: number, callbackPath: string, timeoutMs: number) => Promise<LoopbackHandle>;
  awaitLoopback: (handleId: string) => Promise<LoopbackResult>;
  cancelLoopback: (handleId: string) => Promise<void>;
}

export interface AccountFeatureEntryProps {
  descriptor: AccountFeatureDescriptor;
  api: AccountFeatureApi;
}

interface AccountFeatureModule {
  default: ComponentType<AccountFeatureEntryProps>;
  featureId: string;
  frontendEntry: string;
}

interface HostResponse {
  ok: boolean;
  data?: Record<string, unknown>;
  error?: { code: string; message: string; retryable: boolean };
}

interface DiscoveryPayload {
  features?: AccountFeatureDescriptor[];
  failures?: Array<{ featureId: string; code: string }>;
}

const entryModules = import.meta.glob<AccountFeatureModule>(
  "../../../plugins/providers/builtin/*/frontend/account_entry.tsx",
  { eager: true },
);

class PluginBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? (
      <div role="alert" className="ow-page-frame rounded-2xl p-5 text-sm text-[var(--ow-red)]">
        账号插件页面加载失败，请重新打开账号页。
      </div>
    ) : this.props.children;
  }
}

export function AccountFeatureHost({ active }: { active: boolean }) {
  const [features, setFeatures] = useState<AccountFeatureDescriptor[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setError("");
    void tauriInvoke<HostResponse>("list_account_features")
      .then((response) => {
        if (disposed) return;
        if (!response.ok) throw new Error(response.error?.message || "账号插件发现失败");
        const payload = (response.data || {}) as DiscoveryPayload;
        const next = Array.isArray(payload.features) ? payload.features : [];
        setFeatures(next);
        setSelectedId((current) => next.some((item) => item.feature_id === current) ? current : (next[0]?.feature_id || ""));
      })
      .catch(() => {
        if (disposed) return;
        setFeatures([]);
        setError("账号插件发现失败");
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => { disposed = true; };
  }, [retryKey]);

  const descriptor = features.find((item) => item.feature_id === selectedId) || features[0];
  const entry = useMemo(() => {
    if (!descriptor) return undefined;
    return Object.values(entryModules).find(
      (candidate) => candidate.featureId === descriptor.feature_id && candidate.frontendEntry === descriptor.frontend_entry,
    );
  }, [descriptor]);

  const api = useMemo<AccountFeatureApi | null>(() => {
    if (!descriptor) return null;
    const featureId = descriptor.feature_id;
    return {
      invoke: async (action, payload = {}, handles = []) => {
        const response = await tauriInvoke<HostResponse>("invoke_account_feature", {
          featureId,
          action,
          payload,
          capabilityHandles: handles,
        });
        if (!response.ok) throw new Error(response.error?.message || "账号操作失败");
        return response.data || {};
      },
      chooseOpen: () => tauriInvoke("choose_account_feature_file", { featureId }),
      chooseSave: (suggestedName) => tauriInvoke("choose_account_feature_save", { featureId, suggestedName }),
      openBrowser: (url) => tauriInvoke("open_account_feature_browser", { url }),
      beginLoopback: (preferredPort, callbackPath, timeoutMs) => tauriInvoke("begin_account_feature_loopback", { featureId, preferredPort, callbackPath, timeoutMs }),
      awaitLoopback: (handleId) => tauriInvoke("await_account_feature_loopback", { featureId, handleId }),
      cancelLoopback: async (handleId) => { await tauriInvoke("cancel_account_feature_loopback", { featureId, handleId }); },
    };
  }, [descriptor]);

  if (!active) return null;
  if (loading) {
    return <div aria-live="polite" className="grid min-h-0 flex-1 place-items-center text-sm text-[var(--ow-muted)]">正在加载账号插件…</div>;
  }
  if (error) {
    return (
      <div className="p-5 sm:p-6"><div role="alert" className="ow-page-frame rounded-2xl p-5">
        <p className="text-sm font-semibold text-[var(--ow-red)]">{error}</p>
        <button type="button" className="ow-btn mt-4 rounded-xl px-4 py-2 text-sm font-bold" onClick={() => setRetryKey((value) => value + 1)}>重试</button>
      </div></div>
    );
  }
  if (!descriptor || !api) return null;
  if (!entry) {
    return <div role="alert" className="m-5 ow-page-frame rounded-2xl p-5 text-sm text-[var(--ow-red)]">账号插件前端入口不匹配。</div>;
  }
  const Entry = entry.default;
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-5 sm:p-6">
      {features.length > 1 && (
        <div className="mb-4 flex justify-end">
          <label className="text-sm font-semibold text-[var(--ow-muted)]">平台
            <select className="ml-2 rounded-xl border border-[var(--ow-line)] bg-[var(--ow-panel)] px-3 py-2 text-[var(--ow-text)]" value={descriptor.feature_id} onChange={(event) => setSelectedId(event.target.value)}>
              {features.map((item) => <option key={item.feature_id} value={item.feature_id}>{item.label}</option>)}
            </select>
          </label>
        </div>
      )}
      <PluginBoundary><Entry descriptor={descriptor} api={api} /></PluginBoundary>
    </div>
  );
}
