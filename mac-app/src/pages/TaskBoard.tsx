import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Channel, invoke } from "@tauri-apps/api/core";
import { useI18n } from "../i18n";
import {
  fetchClaudeSessions,
  fetchClaudeMessages,
  fetchCodexSessions,
  fetchCodexThreadState,
  fetchProviderMetadata,
  fetchProviderSession,
  fetchProviderSessions,
} from "../components/session-browser/api";
import { normalizeGenericProviderSessions } from "../components/session-browser/sessionData";
import { type UnifiedSession } from "../components/session-browser/presentation";
import { visibleSessionProviders } from "../utils/sessionProviders.js";
import {
  buildTaskBoardModel,
  type TaskBoardSessionActivity,
  type TaskBoardState,
  type TaskBoardTask,
} from "../utils/taskBoard.js";
import type {
  ClaudeSession,
  CodexSession,
  DashboardState,
  ProviderMetadata,
  SessionTurn,
} from "../types";

export interface TaskBoardOpenSessionTarget {
  providerId: string;
  sessionId: string;
  workspace?: string;
}

interface Props {
  onOpenSession: (target: TaskBoardOpenSessionTarget) => void;
  sessionActivities?: TaskBoardSessionActivity[];
  onSessionActivitiesChange?: (activities: TaskBoardSessionActivity[]) => void;
}

const DEFAULT_TASK_BOARD_STATE: TaskBoardState = {
  version: 1,
  pinned: [],
};

const PINNED_PREVIEW_HYDRATION_LIMIT = 12;
const LOW_SIGNAL_PREVIEW_HYDRATION_LIMIT = 16;
const SESSION_PREVIEW_HYDRATION_TIMEOUT_MS = 1200;
const TASK_BOARD_ACTIVITY_REFRESH_TIMEOUT_MS = 1500;
const TASK_BOARD_SESSION_LIST_REFRESH_TIMEOUT_MS = 2000;

interface TaskBoardActivityStreamEvent {
  kind: "snapshot" | "activity" | "remove" | "error";
  activities?: TaskBoardSessionActivity[];
  activity?: TaskBoardSessionActivity | null;
  providerId?: string;
  sessionId?: string;
  error?: string | null;
}

interface RefreshOptions {
  includeActivities?: boolean;
}

type TaskBoardApprovalAction = "exec_allow" | "exec_deny";

function taskActivityKey(activity: TaskBoardSessionActivity) {
  return `${activity.providerId}:${activity.sessionId}`;
}

function taskSessionKey(providerId: string, sessionId: string) {
  return `${providerId}:${sessionId}`;
}

function normalizedBoardText(value: unknown) {
  return typeof value === "string" ? value.trim().replace(/\s+/g, " ") : "";
}

function isLowSignalBoardText(value: unknown) {
  const text = normalizedBoardText(value).toLowerCase();
  if (!text) {
    return true;
  }
  if (text.length <= 2) {
    return true;
  }
  return ["ok", "done", "yes", "no", "test", "ping"].includes(text);
}

function upsertSessionActivity(
  activities: TaskBoardSessionActivity[],
  activity: TaskBoardSessionActivity,
) {
  const key = taskActivityKey(activity);
  const next = activities.filter((item) => taskActivityKey(item) !== key);
  next.unshift(activity);
  return next;
}

function removeSessionActivity(
  activities: TaskBoardSessionActivity[],
  providerId: string,
  sessionId: string,
) {
  return activities.filter((item) => item.providerId !== providerId || item.sessionId !== sessionId);
}

function formatRelativeTime(epochMs: number | null, nowMs: number, texts: ReturnType<typeof useI18n>["t"]) {
  if (!epochMs) {
    return texts.common.unknown;
  }
  const seconds = Math.max(0, Math.floor((nowMs - epochMs) / 1000));
  if (seconds < 60) {
    return texts.common.secondsAgo(seconds);
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return texts.common.minutesAgo(minutes);
  }
  return texts.common.hoursAgo(Math.floor(minutes / 60));
}

function formatLoadError(error: string, texts: ReturnType<typeof useI18n>["t"]) {
  if (
    error.includes("reading 'invoke'") ||
    error.includes("__TAURI_INTERNALS__") ||
    error.includes("not a function")
  ) {
    return texts.taskBoard.nativeDataUnavailable;
  }
  return error;
}

function toCodexSession(session: CodexSession, workspaceFallback: string): UnifiedSession {
  return {
    id: session.threadId,
    type: "codex",
    workspace: session.cwd || workspaceFallback,
    title: session.title || session.threadId,
    archived: session.archived ?? false,
    raw: session,
  };
}

function toClaudeSession(session: ClaudeSession, workspaceFallback: string): UnifiedSession {
  return {
    id: session.sessionId,
    type: "claude",
    workspace: session.workspace || workspaceFallback,
    title: session.title || session.sessionId,
    archived: session.archived ?? false,
    raw: session,
  };
}

function lastTurnMessage(turns: SessionTurn[]) {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const content = turns[index]?.content?.trim();
    if (content) {
      return content;
    }
  }
  return null;
}

async function readSessionLastMessage(session: UnifiedSession) {
  if (session.type === "codex") {
    const rolloutPath = (session.raw as CodexSession).rolloutPath;
    if (!rolloutPath) {
      return null;
    }
    return lastTurnMessage((await fetchCodexThreadState(rolloutPath)).turns);
  }
  if (session.type === "claude") {
    return lastTurnMessage(await fetchClaudeMessages(session.id, session.workspace));
  }
  return lastTurnMessage(await fetchProviderSession(session.type, session.id, session.workspace));
}

async function readSessionLastMessageWithTimeout(
  session: UnifiedSession,
  timeoutMs = SESSION_PREVIEW_HYDRATION_TIMEOUT_MS,
) {
  let timer: number | null = null;
  try {
    return await Promise.race([
      readSessionLastMessage(session),
      new Promise<null>((resolve) => {
        timer = window.setTimeout(() => resolve(null), timeoutMs);
      }),
    ]);
  } finally {
    if (timer !== null) {
      window.clearTimeout(timer);
    }
  }
}

async function withTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
  label: string,
): Promise<T> {
  let timer: number | null = null;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_, reject) => {
        timer = window.setTimeout(() => {
          reject(new Error(`${label} timed out after ${timeoutMs}ms`));
        }, timeoutMs);
      }),
    ]);
  } finally {
    if (timer !== null) {
      window.clearTimeout(timer);
    }
  }
}

async function loadTaskBoardProviderSessions(
  provider: ProviderMetadata,
  workspaceFallback: string,
): Promise<UnifiedSession[]> {
  if (provider.id === "codex") {
    return (await fetchCodexSessions()).map((session) =>
      toCodexSession(session, workspaceFallback),
    );
  }
  if (provider.id === "claude") {
    return (await fetchClaudeSessions()).map((session) =>
      toClaudeSession(session, workspaceFallback),
    );
  }
  return normalizeGenericProviderSessions(
    provider.id,
    await fetchProviderSessions(provider.id),
    workspaceFallback,
  );
}

async function hydratePinnedSessionPreviews(
  sessions: UnifiedSession[],
  taskBoardState: TaskBoardState,
) {
  const pinnedKeys = new Set(
    taskBoardState.pinned.map((item) => taskSessionKey(item.providerId, item.sessionId)),
  );
  if (pinnedKeys.size === 0) {
    return hydrateLowSignalSessionPreviews(sessions);
  }

  const pinnedUpdatedAtByKey = new Map(
    taskBoardState.pinned.map((item) => [
      taskSessionKey(item.providerId, item.sessionId),
      item.updatedAtEpoch ?? 0,
    ]),
  );
  const pinnedCandidates = sessions
    .filter((session) => pinnedKeys.has(taskSessionKey(session.type, session.id)))
    .sort((left, right) => {
      const leftUpdatedAt = pinnedUpdatedAtByKey.get(taskSessionKey(left.type, left.id)) ?? 0;
      const rightUpdatedAt = pinnedUpdatedAtByKey.get(taskSessionKey(right.type, right.id)) ?? 0;
      return rightUpdatedAt - leftUpdatedAt;
    })
    .slice(0, PINNED_PREVIEW_HYDRATION_LIMIT);
  const hydrationKeys = new Set(
    pinnedCandidates.map((session) => taskSessionKey(session.type, session.id)),
  );

  const hydrated = await Promise.all(sessions.map(async (session) => {
    if (!hydrationKeys.has(taskSessionKey(session.type, session.id))) {
      return session;
    }
    try {
      const lastMessage = await readSessionLastMessageWithTimeout(session);
      if (!lastMessage) {
        return session;
      }
      return {
        ...session,
        raw: {
          ...(session.raw ?? {}),
          lastMessage,
        },
      };
    } catch (lastMessageError) {
      console.warn(`Failed to load pinned session preview for ${session.type}:${session.id}`, lastMessageError);
      return session;
    }
  }));
  return hydrateLowSignalSessionPreviews(hydrated);
}

async function hydrateLowSignalSessionPreviews(
  sessions: UnifiedSession[],
) {
  const lowSignalCandidates = sessions
    .filter((session) => {
      const raw = session.raw ?? {};
      const preview = raw.lastMessage ?? raw.last_message ?? raw.preview ?? raw.summary ?? "";
      return isLowSignalBoardText(session.title) || isLowSignalBoardText(preview);
    })
    .sort((left, right) => {
      const leftUpdatedAt = Number((left.raw as Record<string, unknown> | undefined)?.updatedAt ?? (left.raw as Record<string, unknown> | undefined)?.updated_at ?? 0);
      const rightUpdatedAt = Number((right.raw as Record<string, unknown> | undefined)?.updatedAt ?? (right.raw as Record<string, unknown> | undefined)?.updated_at ?? 0);
      return rightUpdatedAt - leftUpdatedAt;
    })
    .slice(0, LOW_SIGNAL_PREVIEW_HYDRATION_LIMIT);
  const hydrationKeys = new Set(
    lowSignalCandidates.map((session) => taskSessionKey(session.type, session.id)),
  );
  if (hydrationKeys.size === 0) {
    return sessions;
  }

  return Promise.all(sessions.map(async (session) => {
    if (!hydrationKeys.has(taskSessionKey(session.type, session.id))) {
      return session;
    }
    try {
      const lastMessage = await readSessionLastMessageWithTimeout(session);
      if (!lastMessage || isLowSignalBoardText(lastMessage)) {
        return session;
      }
      return {
        ...session,
        raw: {
          ...(session.raw ?? {}),
          lastMessage,
        },
      };
    } catch (lastMessageError) {
      console.warn(`Failed to load low-signal session preview for ${session.type}:${session.id}`, lastMessageError);
      return session;
    }
  }));
}

function taskAccent(providerId: string) {
  if (providerId === "codex") {
    return {
      dot: "bg-violet-500",
      chip: "border-violet-100 bg-violet-50 text-violet-700",
      card: "hover:border-violet-200 hover:bg-violet-50/50",
    };
  }
  if (providerId === "claude") {
    return {
      dot: "bg-slate-500",
      chip: "border-slate-200 bg-slate-100 text-slate-700",
      card: "hover:border-slate-300 hover:bg-slate-50/70",
    };
  }
  return {
    dot: "bg-blue-500",
    chip: "border-blue-100 bg-blue-50 text-blue-700",
    card: "hover:border-blue-200 hover:bg-blue-50/50",
  };
}

function laneTone(tone: "needsAttention" | "running" | "pinned") {
  if (tone === "needsAttention") {
    return {
      dot: "bg-amber-500",
      header: "text-amber-800",
      lane: "bg-amber-50/35",
      card: "border-amber-200 bg-amber-50/60",
    };
  }
  if (tone === "running") {
    return {
      dot: "bg-blue-500",
      header: "text-blue-800",
      lane: "bg-blue-50/35",
      card: "border-blue-200 bg-blue-50/56",
    };
  }
  return {
    dot: "bg-emerald-500",
    header: "text-emerald-800",
    lane: "bg-emerald-50/32",
    card: "border-[var(--ow-line-soft)] bg-white/86",
  };
}

function statusLabel(task: TaskBoardTask, texts: ReturnType<typeof useI18n>["t"]) {
  if (task.needsAttention) {
    return texts.taskBoard.statusNeedsAttention;
  }
  if (task.running) {
    return texts.taskBoard.statusRunning;
  }
  return texts.taskBoard.statusPinned;
}

function isApprovalTask(task: TaskBoardTask) {
  return task.needsAttention && !task.mirroredOnly && task.attentionKind === "approval" && Boolean(task.requestId);
}

function TaskCard({
  task,
  tone,
  nowMs,
  onOpen,
  onTogglePin,
  selected,
  selectable,
  approvalBusy,
  onToggleSelect,
  onApprovalAction,
}: {
  task: TaskBoardTask;
  tone: "needsAttention" | "running" | "pinned";
  nowMs: number;
  onOpen: (task: TaskBoardTask) => void;
  onTogglePin: (task: TaskBoardTask) => void;
  selected: boolean;
  selectable: boolean;
  approvalBusy: boolean;
  onToggleSelect: (task: TaskBoardTask) => void;
  onApprovalAction: (task: TaskBoardTask, action: TaskBoardApprovalAction) => void;
}) {
  const { t } = useI18n();
  const accent = taskAccent(task.providerId);
  const toneClasses = laneTone(tone);
  const pinLabel = task.pinned ? t.taskBoard.unpin : t.taskBoard.pin;
  const showPinText = task.pinned && tone === "pinned";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(task)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen(task);
        }
      }}
      className={`group flex min-h-[250px] flex-col rounded-md border p-3 text-left shadow-[0_2px_10px_rgba(15,23,42,0.035)] transition-colors focus:outline-none focus:ring-2 focus:ring-blue-300/70 ${toneClasses.card} ${accent.card}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="line-clamp-2 text-sm font-extrabold leading-5 text-slate-950">
            {task.title}
          </p>
          <p className="mt-1 truncate text-xs font-semibold text-slate-500">
            {task.workspace || t.sessions.workspaceFallback}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {selectable ? (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onToggleSelect(task);
              }}
              aria-pressed={selected}
              aria-label={selected ? t.taskBoard.clearSelection : t.taskBoard.selectedApprovals(1)}
              title={selected ? t.taskBoard.clearSelection : t.taskBoard.selectedApprovals(1)}
              className={`inline-flex h-7 w-7 items-center justify-center rounded-md border text-xs font-extrabold transition-colors ${
                selected
                  ? "border-blue-500 bg-blue-600 text-white"
                  : "border-slate-200 bg-white/78 text-slate-500 hover:text-slate-900"
              }`}
            >
              {selected ? "✓" : "+"}
            </button>
          ) : null}
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onTogglePin(task);
            }}
            aria-pressed={task.pinned}
            aria-label={pinLabel}
            title={pinLabel}
            className={`inline-flex h-7 shrink-0 items-center justify-center rounded-md border border-slate-200 bg-white/78 text-slate-500 transition-colors hover:text-slate-900 ${
              showPinText ? "gap-1.5 px-2" : "w-7"
            }`}
          >
            <svg className={`h-3.5 w-3.5 ${task.pinned ? "fill-current" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.9" d="M11.05 3.6a1 1 0 011.9 0l1.7 5.24h5.5a1 1 0 01.59 1.81l-4.45 3.23 1.7 5.24a1 1 0 01-1.54 1.12L12 17.01l-4.45 3.23a1 1 0 01-1.54-1.12l1.7-5.24-4.45-3.23a1 1 0 01.59-1.81h5.5l1.7-5.24z" />
            </svg>
            {showPinText ? (
              <span className="text-[11px] font-semibold">{pinLabel}</span>
            ) : null}
          </button>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <span className={`inline-flex max-w-full items-center gap-1.5 rounded-full border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.08em] ${accent.chip}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${accent.dot}`} />
          <span className="truncate">{task.providerLabel}</span>
        </span>
        <span className="inline-flex max-w-full rounded-full border border-slate-200 bg-white/75 px-2 py-1 text-[10px] font-bold text-slate-500">
          <span className="truncate">{statusLabel(task, t)}</span>
        </span>
      </div>

      {task.preview ? (
        <div className="mt-3 overflow-hidden rounded bg-white/60 px-2.5 py-2">
          <p
            className="overflow-hidden text-xs font-medium leading-5 text-slate-600"
            style={{
              display: "-webkit-box",
              WebkitBoxOrient: "vertical",
              WebkitLineClamp: 3,
              maxHeight: "3.75rem",
            }}
          >
            {task.preview}
          </p>
        </div>
      ) : null}

      {selectable ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={approvalBusy}
            onClick={(event) => {
              event.stopPropagation();
              onApprovalAction(task, "exec_allow");
            }}
            className="inline-flex h-8 items-center rounded-md bg-emerald-600 px-3 text-xs font-extrabold text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-emerald-300"
          >
            {t.taskBoard.approve}
          </button>
          <button
            type="button"
            disabled={approvalBusy}
            onClick={(event) => {
              event.stopPropagation();
              onApprovalAction(task, "exec_deny");
            }}
            className="inline-flex h-8 items-center rounded-md border border-rose-200 bg-white px-3 text-xs font-extrabold text-rose-700 transition-colors hover:bg-rose-50 disabled:cursor-not-allowed disabled:border-rose-100 disabled:text-rose-300"
          >
            {t.taskBoard.deny}
          </button>
        </div>
      ) : null}

      <div className="mt-auto flex items-center justify-between gap-2 pt-3 text-[11px] font-semibold text-slate-400">
        {task.statusReason ? (
          <span className="truncate" title={task.statusReason}>
            {task.statusReason}
          </span>
        ) : (
          <span />
        )}
        <span className="shrink-0">
          {formatRelativeTime(task.updatedAtEpochMs, nowMs, t)}
        </span>
      </div>
    </div>
  );
}

function BoardLane({
  title,
  count,
  empty,
  tasks,
  tone,
  nowMs,
  onOpen,
  onTogglePin,
  selectedApprovalTaskIds,
  busyApprovalTaskIds,
  onToggleSelect,
  onApprovalAction,
}: {
  title: string;
  count: number;
  empty: string;
  tasks: TaskBoardTask[];
  tone: "needsAttention" | "running" | "pinned";
  nowMs: number;
  onOpen: (task: TaskBoardTask) => void;
  onTogglePin: (task: TaskBoardTask) => void;
  selectedApprovalTaskIds: Set<string>;
  busyApprovalTaskIds: Set<string>;
  onToggleSelect: (task: TaskBoardTask) => void;
  onApprovalAction: (task: TaskBoardTask, action: TaskBoardApprovalAction) => void;
}) {
  const toneClasses = laneTone(tone);

  return (
    <section className={`flex min-h-0 flex-col border-r border-[var(--ow-line-soft)] last:border-r-0 ${toneClasses.lane}`}>
      <div className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-[var(--ow-line-soft)] bg-slate-50/82 px-3">
        <h2 className={`flex min-w-0 items-center gap-2 truncate text-sm font-extrabold ${toneClasses.header}`}>
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${toneClasses.dot}`} />
          <span className="truncate">{title}</span>
        </h2>
        <span className="shrink-0 rounded-full border border-slate-200 bg-white/78 px-2 py-1 text-[11px] font-extrabold text-slate-500">
          {count}
        </span>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2">
        {tasks.length === 0 ? (
          <div className="flex min-h-[160px] items-center justify-center rounded-md border border-dashed border-slate-200 bg-white/58 px-4 text-center text-sm font-semibold text-slate-400">
            {empty}
          </div>
        ) : (
          tasks.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              tone={tone}
              nowMs={nowMs}
              onOpen={onOpen}
              onTogglePin={onTogglePin}
              selected={selectedApprovalTaskIds.has(task.id)}
              selectable={isApprovalTask(task)}
              approvalBusy={busyApprovalTaskIds.has(task.id)}
              onToggleSelect={onToggleSelect}
              onApprovalAction={onApprovalAction}
            />
          ))
        )}
      </div>
    </section>
  );
}

export function TaskBoard({
  onOpenSession,
  sessionActivities: sharedSessionActivities,
  onSessionActivitiesChange,
}: Props) {
  const { t } = useI18n();
  const [providers, setProviders] = useState<ProviderMetadata[]>([]);
  const [dashboardState, setDashboardState] = useState<DashboardState | null>(null);
  const [taskBoardState, setTaskBoardState] = useState<TaskBoardState>(DEFAULT_TASK_BOARD_STATE);
  const [localSessionActivities, setLocalSessionActivities] = useState<TaskBoardSessionActivity[]>([]);
  const [sessions, setSessions] = useState<UnifiedSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [selectedApprovalTaskIds, setSelectedApprovalTaskIds] = useState<string[]>([]);
  const [busyApprovalTaskIds, setBusyApprovalTaskIds] = useState<string[]>([]);
  const refreshSequenceRef = useRef(0);

  const providerLabels = useMemo(
    () => Object.fromEntries(
      providers.map((provider) => [provider.id, provider.label || provider.id]),
    ) as Record<string, string>,
    [providers],
  );

  const refresh = useCallback(async ({ includeActivities = true }: RefreshOptions = {}) => {
    setRefreshing(true);
    const refreshSequence = refreshSequenceRef.current + 1;
    refreshSequenceRef.current = refreshSequence;
    try {
      const [nextProviders, nextDashboard, nextTaskBoardState] = await Promise.all([
        fetchProviderMetadata(),
        invoke<DashboardState>("get_dashboard_state"),
        invoke<TaskBoardState>("get_task_board_state"),
      ]);
      const nextSessionActivities = includeActivities
        ? await withTimeout(
          invoke<TaskBoardSessionActivity[]>("get_task_board_session_activities"),
          TASK_BOARD_ACTIVITY_REFRESH_TIMEOUT_MS,
          "load task board session activities",
        ).catch((activityError) => {
          console.warn("Failed to load task board session activity projection", activityError);
          return [];
        })
        : null;
      setProviders(nextProviders);
      setDashboardState(nextDashboard);
      setTaskBoardState(nextTaskBoardState);
      if (nextSessionActivities !== null) {
        if (onSessionActivitiesChange) {
          onSessionActivitiesChange(nextSessionActivities);
        } else {
          setLocalSessionActivities(nextSessionActivities);
        }
      }
      setNowMs(Date.now());
      setError(null);
      setLoading(false);

      const visibleProviders = visibleSessionProviders(nextProviders) as ProviderMetadata[];
      const sessionResults = await Promise.all(
        visibleProviders.map(async (provider) => {
          try {
            return await withTimeout(
              loadTaskBoardProviderSessions(provider, t.sessions.workspaceFallback),
              TASK_BOARD_SESSION_LIST_REFRESH_TIMEOUT_MS,
              `load task board sessions for ${provider.id}`,
            );
          } catch (sessionError) {
            console.warn(`Failed to load task board sessions for ${provider.id}`, sessionError);
            return [];
          }
        }),
      );
      const flatSessions = sessionResults.flat();
      setSessions(flatSessions);
      setNowMs(Date.now());
      void hydratePinnedSessionPreviews(flatSessions, nextTaskBoardState)
        .then((hydratedSessions) => {
          if (refreshSequenceRef.current !== refreshSequence) {
            return;
          }
          setSessions(hydratedSessions);
          setNowMs(Date.now());
        })
        .catch((hydrationError) => {
          console.warn("Failed to hydrate task board session previews", hydrationError);
        });
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [onSessionActivitiesChange, t.sessions.workspaceFallback]);

  useEffect(() => {
    void refresh({ includeActivities: true });
  }, [refresh]);

  useEffect(() => {
    if (sharedSessionActivities !== undefined) {
      return;
    }
    const channel = new Channel<TaskBoardActivityStreamEvent>();
    let activeStreamId: number | null = null;
    let disposed = false;
    channel.onmessage = (event) => {
      if (event.kind === "snapshot") {
        setLocalSessionActivities(event.activities ?? []);
        setNowMs(Date.now());
        setLoading(false);
        return;
      }
      if (event.kind === "activity" && event.activity) {
        const activity = event.activity;
        setLocalSessionActivities((current) => upsertSessionActivity(current, activity));
        setNowMs(Date.now());
        setLoading(false);
        return;
      }
      if (event.kind === "remove" && event.providerId && event.sessionId) {
        setLocalSessionActivities((current) => removeSessionActivity(current, event.providerId!, event.sessionId!));
        setNowMs(Date.now());
        setLoading(false);
        return;
      }
      if (event.kind === "error" && event.error) {
        console.warn("Task board activity stream failed", event.error);
      }
    };

    void invoke<number>("start_task_board_activity_stream", { channel })
      .then((streamId) => {
        if (disposed) {
          void invoke("stop_task_board_activity_stream", { streamId }).catch((streamError) => {
            console.warn("Failed to stop task board activity stream", streamError);
          });
          return;
        }
        activeStreamId = streamId;
      })
      .catch((streamError) => {
        console.warn("Failed to start task board activity stream", streamError);
      });

    return () => {
      disposed = true;
      if (activeStreamId === null) {
        return;
      }
      void invoke("stop_task_board_activity_stream", { streamId: activeStreamId }).catch((streamError) => {
        console.warn("Failed to stop task board activity stream", streamError);
      });
    };
  }, [sharedSessionActivities]);

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const updateTaskBoardState = useCallback(async (
    command: "pin_task_board_session" | "unpin_task_board_session",
    task: TaskBoardTask,
  ) => {
    try {
      const nextState = await invoke<TaskBoardState>(command, {
        providerId: task.providerId,
        sessionId: task.sessionId,
      });
      setTaskBoardState(nextState);
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }, []);

  const handleTogglePin = useCallback((task: TaskBoardTask) => {
    void updateTaskBoardState(
      task.pinned ? "unpin_task_board_session" : "pin_task_board_session",
      task,
    );
  }, [updateTaskBoardState]);

  const handleOpen = useCallback((task: TaskBoardTask) => {
    onOpenSession({
      providerId: task.providerId,
      sessionId: task.sessionId,
      workspace: task.workspace,
    });
  }, [onOpenSession]);

  const board = useMemo(
    () => buildTaskBoardModel({
      sessions,
      sessionActivities: sharedSessionActivities ?? localSessionActivities,
      dashboardState,
      taskBoardState,
      providerLabels,
      nowEpochMs: nowMs,
    }),
    [dashboardState, nowMs, providerLabels, sharedSessionActivities, localSessionActivities, sessions, taskBoardState],
  );
  const selectableApprovalTasks = useMemo(
    () => board.needsAttention.filter(isApprovalTask),
    [board.needsAttention],
  );
  const selectableApprovalTaskIdSet = useMemo(
    () => new Set(selectableApprovalTasks.map((task) => task.id)),
    [selectableApprovalTasks],
  );
  const selectedApprovalTaskIdSet = useMemo(
    () => new Set(selectedApprovalTaskIds),
    [selectedApprovalTaskIds],
  );
  const busyApprovalTaskIdSet = useMemo(
    () => new Set(busyApprovalTaskIds),
    [busyApprovalTaskIds],
  );

  useEffect(() => {
    setSelectedApprovalTaskIds((current) => current.filter((id) => selectableApprovalTaskIdSet.has(id)));
  }, [selectableApprovalTaskIdSet]);

  const handleToggleApprovalSelection = useCallback((task: TaskBoardTask) => {
    if (!isApprovalTask(task)) {
      return;
    }
    setSelectedApprovalTaskIds((current) => (
      current.includes(task.id)
        ? current.filter((id) => id !== task.id)
        : [...current, task.id]
    ));
  }, []);

  const handleApprovalAction = useCallback(async (
    tasks: TaskBoardTask[],
    action: TaskBoardApprovalAction,
  ) => {
    const candidateTasks = tasks.filter(isApprovalTask);
    if (candidateTasks.length === 0) {
      return;
    }

    const taskIds = candidateTasks.map((task) => task.id);
    setBusyApprovalTaskIds((current) => Array.from(new Set([...current, ...taskIds])));

    try {
      const results = await Promise.all(candidateTasks.map(async (task) => {
        try {
          await invoke("reply_task_board_approval", {
            providerId: task.providerId,
            workspaceId: task.workspaceId,
            workspacePath: task.workspacePath || task.workspace,
            sessionId: task.sessionId,
            requestId: task.requestId,
            action,
            approvalSource: task.approvalSource || null,
            command: null,
            reason: task.statusReason || null,
          });
          return { taskId: task.id, error: null };
        } catch (approvalError) {
          return { taskId: task.id, error: `${task.title}: ${String(approvalError)}` };
        }
      }));

      const failedResults = results.filter((item) => item.error);
      const failedTaskIds = new Set(failedResults.map((item) => item.taskId));
      const succeededTaskIds = taskIds.filter((taskId) => !failedTaskIds.has(taskId));

      if (failedResults.length > 0) {
        setActionError(t.taskBoard.approvalReplyFailed(failedResults.map((item) => item.error).join("； ")));
      } else {
        setActionError(null);
      }

      setSelectedApprovalTaskIds((current) => current.filter((id) => !succeededTaskIds.includes(id)));
      await refresh({ includeActivities: true });
    } finally {
      setBusyApprovalTaskIds((current) => current.filter((id) => !taskIds.includes(id)));
    }
  }, [refresh, t.taskBoard]);

  const handleSingleApprovalAction = useCallback((task: TaskBoardTask, action: TaskBoardApprovalAction) => {
    void handleApprovalAction([task], action);
  }, [handleApprovalAction]);

  const handleBatchApprovalAction = useCallback((action: TaskBoardApprovalAction) => {
    const selectedTasks = selectableApprovalTasks.filter((task) => selectedApprovalTaskIdSet.has(task.id));
    void handleApprovalAction(selectedTasks, action);
  }, [handleApprovalAction, selectableApprovalTasks, selectedApprovalTaskIdSet]);

  return (
    <div className="ow-page-frame flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-[30px]">
      <div className="flex shrink-0 flex-col gap-4 border-b border-[var(--ow-line-soft)] px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-extrabold uppercase tracking-[0.14em] text-blue-600">
            {t.taskBoard.eyebrow}
          </p>
          <h1 className="mt-1 truncate text-2xl font-extrabold text-gray-950">
            {t.taskBoard.title}
          </h1>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="ow-segment grid grid-cols-3 rounded-2xl p-1">
            {[
              [t.taskBoard.needsAttentionColumn, board.counts.needsAttention],
              [t.taskBoard.runningColumn, board.counts.running],
              [t.taskBoard.pinnedColumn, board.counts.pinnedIdle],
            ].map(([label, count]) => (
              <div
                key={label}
                className="rounded-xl px-3 py-1.5 text-center text-xs font-extrabold text-slate-600"
              >
                <span>{label}</span>
                <span className="ml-1 text-slate-400">{count}</span>
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={refreshing}
            className="ow-btn inline-flex h-10 items-center gap-2 rounded-2xl px-4 text-sm font-extrabold text-slate-700 disabled:opacity-60"
            title={t.taskBoard.refresh}
          >
            <svg
              className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v6h6M20 20v-6h-6M20 9A8 8 0 006.34 5.34L4 8m16 8l-2.34 2.66A8 8 0 014 15" />
            </svg>
            {refreshing ? t.taskBoard.refreshing : t.taskBoard.refresh}
          </button>
        </div>
      </div>

      {selectedApprovalTaskIds.length > 0 ? (
        <div className="mx-5 mt-4 flex flex-wrap items-center gap-2 rounded-2xl border border-blue-100 bg-blue-50/85 px-4 py-3 text-sm font-semibold text-blue-900">
          <span className="mr-auto">{t.taskBoard.selectedApprovals(selectedApprovalTaskIds.length)}</span>
          <button
            type="button"
            disabled={busyApprovalTaskIds.length > 0}
            onClick={() => handleBatchApprovalAction("exec_allow")}
            className="inline-flex h-9 items-center rounded-xl bg-emerald-600 px-4 text-sm font-extrabold text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-emerald-300"
          >
            {t.taskBoard.approve}
          </button>
          <button
            type="button"
            disabled={busyApprovalTaskIds.length > 0}
            onClick={() => handleBatchApprovalAction("exec_deny")}
            className="inline-flex h-9 items-center rounded-xl border border-rose-200 bg-white px-4 text-sm font-extrabold text-rose-700 transition-colors hover:bg-rose-50 disabled:cursor-not-allowed disabled:border-rose-100 disabled:text-rose-300"
          >
            {t.taskBoard.deny}
          </button>
          <button
            type="button"
            disabled={busyApprovalTaskIds.length > 0}
            onClick={() => setSelectedApprovalTaskIds([])}
            className="inline-flex h-9 items-center rounded-xl border border-slate-200 bg-white px-4 text-sm font-extrabold text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-300"
          >
            {t.taskBoard.clearSelection}
          </button>
        </div>
      ) : null}

      {actionError ? (
        <div className="mx-5 mt-4 rounded-2xl border border-amber-200 bg-amber-50/85 px-4 py-3 text-sm font-semibold text-amber-800">
          {actionError}
        </div>
      ) : null}

      {error ? (
        <div className="mx-5 mt-4 rounded-2xl border border-rose-200 bg-rose-50/85 px-4 py-3 text-sm font-semibold text-rose-700">
          {t.taskBoard.failedToLoad(formatLoadError(error, t))}
        </div>
      ) : null}

      {loading ? (
        <div className="flex min-h-0 flex-1 items-center justify-center text-sm font-semibold text-slate-500">
          {t.common.loading}
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-x-auto p-4">
          <div className="grid h-full min-w-[780px] grid-cols-3 overflow-hidden rounded-lg border border-[var(--ow-line-soft)] bg-white/70">
            <BoardLane
              title={t.taskBoard.needsAttentionColumn}
              count={board.counts.needsAttention}
              empty={t.taskBoard.noNeedsAttentionTasks}
              tasks={board.needsAttention}
              tone="needsAttention"
              nowMs={nowMs}
              onOpen={handleOpen}
              onTogglePin={handleTogglePin}
              selectedApprovalTaskIds={selectedApprovalTaskIdSet}
              busyApprovalTaskIds={busyApprovalTaskIdSet}
              onToggleSelect={handleToggleApprovalSelection}
              onApprovalAction={handleSingleApprovalAction}
            />
            <BoardLane
              title={t.taskBoard.runningColumn}
              count={board.counts.running}
              empty={t.taskBoard.noRunningTasks}
              tasks={board.running}
              tone="running"
              nowMs={nowMs}
              onOpen={handleOpen}
              onTogglePin={handleTogglePin}
              selectedApprovalTaskIds={selectedApprovalTaskIdSet}
              busyApprovalTaskIds={busyApprovalTaskIdSet}
              onToggleSelect={handleToggleApprovalSelection}
              onApprovalAction={handleSingleApprovalAction}
            />
            <BoardLane
              title={t.taskBoard.pinnedColumn}
              count={board.counts.pinnedIdle}
              empty={t.taskBoard.noPinnedTasks}
              tasks={board.pinnedIdle}
              tone="pinned"
              nowMs={nowMs}
              onOpen={handleOpen}
              onTogglePin={handleTogglePin}
              selectedApprovalTaskIds={selectedApprovalTaskIdSet}
              busyApprovalTaskIds={busyApprovalTaskIdSet}
              onToggleSelect={handleToggleApprovalSelection}
              onApprovalAction={handleSingleApprovalAction}
            />
          </div>
        </div>
      )}
    </div>
  );
}
