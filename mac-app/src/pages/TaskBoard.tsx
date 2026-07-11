import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Channel, invoke } from "@tauri-apps/api/core";
import { useI18n } from "../i18n";
import {
  fetchProviderMetadata,
  fetchProviderSession,
  fetchProviderSessions,
} from "../components/session-browser/api";
import {
  normalizeGenericProviderSessions,
  readCachedProviderSessionSnapshotRows,
  writeCachedProviderSessionSnapshot,
} from "../components/session-browser/sessionData";
import { type UnifiedSession } from "../components/session-browser/presentation";
import { mergeSessionListSnapshot } from "../utils/sessionBrowserState.js";
import { visibleSessionProviders } from "../utils/sessionProviders.js";
import {
  buildTaskBoardModel,
  collectTaskBoardPreviewHydrationPlan,
  isLowSignalTaskBoardText,
  removeTaskBoardActivity,
  selectRecentConversationTurns,
  taskBoardSessionKey,
  type TaskBoardActivityStreamEvent,
  type TaskBoardSessionActivity,
  type TaskBoardState,
  type TaskBoardTask,
  upsertTaskBoardActivity,
} from "../utils/taskBoard.js";
import type {
  DashboardState,
  ProviderMetadata,
  SessionTurn,
} from "../types";

export interface TaskBoardOpenSessionTarget {
  providerId: string;
  sessionId: string;
  workspace?: string;
  focusComposerKey?: number;
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
const TASK_BOARD_DETAIL_TURN_LIMIT = 6;

interface RefreshOptions {
  includeActivities?: boolean;
  forceProviderRefresh?: boolean;
}

type TaskBoardApprovalAction = "exec_allow" | "exec_deny";
type TaskBoardControlAction = "interrupt" | "recover";

interface PendingTaskBoardControl {
  taskId: string;
  action: TaskBoardControlAction;
  startedAtEpochMs: number;
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

async function hydrateTaskBoardSessionPreviews(
  sessions: UnifiedSession[],
  taskBoardState: TaskBoardState,
) {
  const plan = collectTaskBoardPreviewHydrationPlan({
    sessions,
    taskBoardState,
    pinnedLimit: PINNED_PREVIEW_HYDRATION_LIMIT,
    lowSignalLimit: LOW_SIGNAL_PREVIEW_HYDRATION_LIMIT,
  });
  const hydrationKeys = new Set(plan.keys);
  if (hydrationKeys.size === 0) {
    return sessions;
  }
  const pinnedKeys = new Set(plan.pinnedKeys);

  return Promise.all(sessions.map(async (session) => {
    const key = taskBoardSessionKey(session.type, session.id);
    if (!hydrationKeys.has(key)) {
      return session;
    }
    try {
      const lastMessage = await readSessionLastMessageWithTimeout(session);
      if (!lastMessage) {
        return session;
      }
      if (!pinnedKeys.has(key) && isLowSignalTaskBoardText(lastMessage)) {
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
      console.warn(`Failed to hydrate task board session preview for ${session.type}:${session.id}`, lastMessageError);
      return session;
    }
  }));
}

function taskAccent(providerId: string) {
  const accents = [
    {
      dot: "bg-violet-500",
      chip: "border-violet-100 bg-violet-50 text-violet-700",
      card: "hover:border-violet-200 hover:bg-violet-50/50",
    },
    {
      dot: "bg-sky-500",
      chip: "border-sky-100 bg-sky-50 text-sky-700",
      card: "hover:border-sky-200 hover:bg-sky-50/50",
    },
    {
      dot: "bg-emerald-500",
      chip: "border-emerald-100 bg-emerald-50 text-emerald-700",
      card: "hover:border-emerald-200 hover:bg-emerald-50/50",
    },
    {
      dot: "bg-amber-500",
      chip: "border-amber-100 bg-amber-50 text-amber-700",
      card: "hover:border-amber-200 hover:bg-amber-50/50",
    },
    {
      dot: "bg-slate-500",
      chip: "border-slate-200 bg-slate-100 text-slate-700",
      card: "hover:border-slate-300 hover:bg-slate-50/70",
    },
  ];
  const hash = providerId.split("").reduce((value, char) => ((value * 31) + char.charCodeAt(0)) >>> 0, 0);
  return accents[hash % accents.length];
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
  active,
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
  active: boolean;
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
      aria-selected={active}
      className={`group flex min-h-[132px] flex-col border-b border-[var(--ow-line-soft)] px-3 py-3 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-300/70 ${active ? "bg-blue-50/80 shadow-[inset_3px_0_0_var(--ow-blue)]" : `${toneClasses.card} ${accent.card}`}`}
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

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className={`inline-flex max-w-full items-center gap-1.5 rounded-full border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.08em] ${accent.chip}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${accent.dot}`} />
          <span className="truncate">{task.providerLabel}</span>
        </span>
        <span className="inline-flex max-w-full rounded-full border border-slate-200 bg-white/75 px-2 py-1 text-[10px] font-bold text-slate-500">
          <span className="truncate">{statusLabel(task, t)}</span>
        </span>
      </div>

      {task.preview ? (
        <div className="mt-2 overflow-hidden">
          <p
            className="overflow-hidden text-xs font-medium leading-5 text-slate-600"
            style={{
              display: "-webkit-box",
              WebkitBoxOrient: "vertical",
              WebkitLineClamp: 2,
              maxHeight: "2.5rem",
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
  activeTaskId,
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
  activeTaskId: string | null;
  selectedApprovalTaskIds: Set<string>;
  busyApprovalTaskIds: Set<string>;
  onToggleSelect: (task: TaskBoardTask) => void;
  onApprovalAction: (task: TaskBoardTask, action: TaskBoardApprovalAction) => void;
}) {
  const toneClasses = laneTone(tone);

  return (
    <section className={`border-b border-[var(--ow-line-soft)] last:border-b-0 ${toneClasses.lane}`}>
      <div className="flex h-10 items-center justify-between gap-2 border-b border-[var(--ow-line-soft)] bg-slate-50/82 px-3">
        <h2 className={`flex min-w-0 items-center gap-2 truncate text-sm font-extrabold ${toneClasses.header}`}>
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${toneClasses.dot}`} />
          <span className="truncate">{title}</span>
        </h2>
        <span className="shrink-0 rounded-full border border-slate-200 bg-white/78 px-2 py-1 text-[11px] font-extrabold text-slate-500">
          {count}
        </span>
      </div>

      <div>
        {tasks.length === 0 ? (
          <div className="flex min-h-[68px] items-center justify-center px-4 text-center text-xs font-semibold text-slate-400">
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
              active={activeTaskId === task.id}
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
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedConversationTurns, setSelectedConversationTurns] = useState<SessionTurn[]>([]);
  const [selectedConversationLoading, setSelectedConversationLoading] = useState(false);
  const [selectedConversationError, setSelectedConversationError] = useState(false);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const [pendingControl, setPendingControl] = useState<PendingTaskBoardControl | null>(null);
  const hasHydratedProviderSessionsRef = useRef(false);
  const refreshSequenceRef = useRef(0);
  const refreshInFlightRef = useRef(false);

  const providerLabels = useMemo(
    () => Object.fromEntries(
      providers.map((provider) => [provider.id, provider.label || provider.id]),
    ) as Record<string, string>,
    [providers],
  );

  const refresh = useCallback(async ({ includeActivities = true, forceProviderRefresh = false }: RefreshOptions = {}) => {
    if (refreshInFlightRef.current) {
      return;
    }
    refreshInFlightRef.current = true;
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

      const cachedSessions = readCachedProviderSessionSnapshotRows(
        visibleSessionProviders(nextProviders).map((provider) => provider.id),
      );
      if (cachedSessions.length > 0) {
        setSessions((current) => mergeSessionListSnapshot(current, cachedSessions));
      }

      const visibleProviders = visibleSessionProviders(nextProviders) as ProviderMetadata[];
      const sessionResults = await Promise.all(
        visibleProviders.map(async (provider) => {
          try {
            const normalizedSessions = normalizeGenericProviderSessions(
              provider.id,
              await fetchProviderSessions(provider.id, { forceRefresh: forceProviderRefresh }),
              t.sessions.workspaceFallback,
            );
            return writeCachedProviderSessionSnapshot(provider.id, normalizedSessions);
          } catch (sessionError) {
            console.warn(`Failed to load task board sessions for ${provider.id}`, sessionError);
            return [];
          }
        }),
      );
      const flatSessions = sessionResults.flat();
      setSessions((current) => mergeSessionListSnapshot(current, flatSessions));
      setNowMs(Date.now());
      void hydrateTaskBoardSessionPreviews(flatSessions, nextTaskBoardState)
        .then((hydratedSessions) => {
          if (refreshSequenceRef.current !== refreshSequence) {
            return;
          }
          setSessions((current) => mergeSessionListSnapshot(current, hydratedSessions));
          setNowMs(Date.now());
        })
        .catch((hydrationError) => {
          console.warn("Failed to hydrate task board session previews", hydrationError);
        });
    } catch (err) {
      setError(String(err));
    } finally {
      refreshInFlightRef.current = false;
      setLoading(false);
      setRefreshing(false);
    }
  }, [onSessionActivitiesChange, t.sessions.workspaceFallback]);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      await refresh({ includeActivities: true });
      if (cancelled || hasHydratedProviderSessionsRef.current) {
        return;
      }
      hasHydratedProviderSessionsRef.current = true;
      await refresh({ includeActivities: false, forceProviderRefresh: true });
    })();

    return () => {
      cancelled = true;
    };
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
        setLocalSessionActivities((current) => upsertTaskBoardActivity(current, activity));
        setNowMs(Date.now());
        setLoading(false);
        return;
      }
      if (event.kind === "remove" && event.providerId && event.sessionId) {
        setLocalSessionActivities((current) => removeTaskBoardActivity(current, event.providerId!, event.sessionId!));
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

  const handleContinue = useCallback((task: TaskBoardTask) => {
    onOpenSession({
      providerId: task.providerId,
      sessionId: task.sessionId,
      workspace: task.workspace,
      focusComposerKey: Date.now(),
    });
  }, [onOpenSession]);

  const handleSelectTask = useCallback((task: TaskBoardTask) => {
    setSelectedTaskId(task.id);
    setMobileDetailOpen(true);
  }, []);

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
  const allTasks = useMemo(
    () => [...board.needsAttention, ...board.running, ...board.recentEnded],
    [board.needsAttention, board.recentEnded, board.running],
  );
  const selectedTask = useMemo(
    () => allTasks.find((task) => task.id === selectedTaskId) ?? null,
    [allTasks, selectedTaskId],
  );

  useEffect(() => {
    if (selectedTask) {
      return;
    }
    const initial = board.needsAttention.find((task) => !task.mirroredOnly)
      ?? board.running[0]
      ?? board.recentEnded[0]
      ?? board.needsAttention[0]
      ?? null;
    setSelectedTaskId(initial?.id ?? null);
  }, [board.needsAttention, board.recentEnded, board.running, selectedTask]);

  useEffect(() => {
    if (!selectedTask) {
      setSelectedConversationTurns([]);
      setSelectedConversationLoading(false);
      setSelectedConversationError(false);
      return;
    }

    let cancelled = false;
    const fallbackTurns = selectRecentConversationTurns([
      { role: "user", content: selectedTask.lastUserMessage },
      { role: "assistant", content: selectedTask.lastAssistantMessage || selectedTask.preview || "" },
    ], TASK_BOARD_DETAIL_TURN_LIMIT) as SessionTurn[];
    setSelectedConversationTurns(fallbackTurns);
    setSelectedConversationLoading(true);
    setSelectedConversationError(false);

    void fetchProviderSession(
      selectedTask.providerId,
      selectedTask.sessionId,
      selectedTask.workspace || null,
    ).then((turns) => {
      if (cancelled) {
        return;
      }
      const recentTurns = selectRecentConversationTurns(
        turns,
        TASK_BOARD_DETAIL_TURN_LIMIT,
      ) as SessionTurn[];
      setSelectedConversationTurns(recentTurns.length > 0 ? recentTurns : fallbackTurns);
      setSelectedConversationLoading(false);
    }).catch((conversationError) => {
      if (cancelled) {
        return;
      }
      console.warn(`Failed to load task board conversation for ${selectedTask.providerId}:${selectedTask.sessionId}`, conversationError);
      setSelectedConversationError(fallbackTurns.length === 0);
      setSelectedConversationLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [selectedTask?.id, selectedTask?.providerId, selectedTask?.sessionId, selectedTask?.workspace]);

  useEffect(() => {
    if (!pendingControl) {
      return;
    }
    const task = allTasks.find((item) => item.id === pendingControl.taskId);
    if (!task) {
      setPendingControl(null);
      return;
    }
    if (pendingControl.action === "interrupt" && (!task.running || !task.canInterrupt)) {
      setPendingControl(null);
      return;
    }
    if (
      pendingControl.action === "recover"
      && (task.running || (task.updatedAtEpochMs ?? 0) > pendingControl.startedAtEpochMs)
    ) {
      setPendingControl(null);
    }
  }, [allTasks, pendingControl]);

  const handleControlAction = useCallback(async (
    task: TaskBoardTask,
    action: TaskBoardControlAction,
  ) => {
    setPendingControl({
      taskId: task.id,
      action,
      startedAtEpochMs: task.updatedAtEpochMs ?? Date.now(),
    });
    setActionError(null);
    try {
      const result = await invoke<{ awaitingProviderEvent?: boolean }>("control_task_board_session", {
        providerId: task.providerId,
        workspaceId: task.workspaceId,
        sessionId: task.sessionId,
        action,
      });
      if (result.awaitingProviderEvent === false) {
        setPendingControl(null);
      }
    } catch (controlError) {
      setPendingControl(null);
      setActionError(`${action === "interrupt" ? "中断" : "恢复"}失败：${String(controlError)}`);
    }
  }, []);
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
      await refresh({ includeActivities: true, forceProviderRefresh: true });
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
          <h1 className="truncate text-base font-bold text-gray-950">
            {t.taskBoard.title}
          </h1>
          <p className="mt-1 text-xs font-medium text-slate-500">集中处理需要你介入的 Agent 工作，并查看真实 Session 状态。</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="ow-segment grid grid-cols-3 rounded-2xl p-1">
            {[
              ["需要你", board.counts.needsAttention],
              ["正在运行", board.counts.running],
              ["最近结束", board.counts.recentEnded],
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
            onClick={() => void refresh({ includeActivities: true, forceProviderRefresh: true })}
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
        <div className="min-h-0 flex-1 p-4">
          <div className="grid h-full min-h-0 overflow-hidden rounded-lg border border-[var(--ow-line-soft)] bg-white/72 lg:grid-cols-[minmax(320px,0.9fr)_minmax(0,1.25fr)]">
            <div className={`${mobileDetailOpen ? "hidden lg:block" : "block"} min-h-0 overflow-y-auto border-b border-[var(--ow-line-soft)] lg:border-b-0 lg:border-r`}>
              <BoardLane
                title="需要你"
                count={board.counts.needsAttention}
                empty="当前没有需要你处理的 Session。"
                tasks={board.needsAttention}
                tone="needsAttention"
                nowMs={nowMs}
                onOpen={handleSelectTask}
                onTogglePin={handleTogglePin}
                activeTaskId={selectedTaskId}
                selectedApprovalTaskIds={selectedApprovalTaskIdSet}
                busyApprovalTaskIds={busyApprovalTaskIdSet}
                onToggleSelect={handleToggleApprovalSelection}
                onApprovalAction={handleSingleApprovalAction}
              />
              <BoardLane
                title="正在运行"
                count={board.counts.running}
                empty="当前没有正在运行的 Session。"
                tasks={board.running}
                tone="running"
                nowMs={nowMs}
                onOpen={handleSelectTask}
                onTogglePin={handleTogglePin}
                activeTaskId={selectedTaskId}
                selectedApprovalTaskIds={selectedApprovalTaskIdSet}
                busyApprovalTaskIds={busyApprovalTaskIdSet}
                onToggleSelect={handleToggleApprovalSelection}
                onApprovalAction={handleSingleApprovalAction}
              />
              <BoardLane
                title="最近结束"
                count={board.counts.recentEnded}
                empty="当前没有最近结束的 Session。"
                tasks={board.recentEnded}
                tone="pinned"
                nowMs={nowMs}
                onOpen={handleSelectTask}
                onTogglePin={handleTogglePin}
                activeTaskId={selectedTaskId}
                selectedApprovalTaskIds={selectedApprovalTaskIdSet}
                busyApprovalTaskIds={busyApprovalTaskIdSet}
                onToggleSelect={handleToggleApprovalSelection}
                onApprovalAction={handleSingleApprovalAction}
              />
            </div>

            <aside className={`${mobileDetailOpen ? "block" : "hidden lg:block"} min-h-0 overflow-y-auto bg-[var(--ow-panel)] p-4`} aria-live="polite">
              {selectedTask ? (
                <div className="mx-auto max-w-3xl">
                  <button type="button" onClick={() => setMobileDetailOpen(false)} className="ow-btn mb-3 h-9 rounded-lg px-3 text-sm font-semibold text-slate-700 lg:hidden">← 返回列表</button>
                  <div className="flex items-start justify-between gap-4 border-b border-[var(--ow-line-soft)] pb-4">
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-slate-500">{selectedTask.providerLabel} · {selectedTask.workspace || t.sessions.workspaceFallback}</p>
                      <h2 className="mt-1 line-clamp-2 text-base font-bold text-slate-950">{selectedTask.title}</h2>
                      <p className="mt-2 text-sm text-slate-600">
                        {selectedTask.statusReason || selectedTask.preview || (selectedTask.running ? "正在执行" : "Session 最近已结束")}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600">
                      {selectedTask.interrupted ? "已中断" : selectedTask.needsAttention ? "需要你" : selectedTask.running ? "运行中" : "已结束"}
                    </span>
                  </div>

                  <dl className="grid grid-cols-[92px_minmax(0,1fr)] gap-x-3 gap-y-2 border-b border-[var(--ow-line-soft)] py-4 text-xs">
                    <dt className="font-semibold text-slate-400">Provider</dt><dd className="truncate text-slate-700">{selectedTask.providerLabel}</dd>
                    <dt className="font-semibold text-slate-400">Workspace</dt><dd className="truncate text-slate-700">{selectedTask.workspace || "—"}</dd>
                    <dt className="font-semibold text-slate-400">Session</dt><dd className="truncate font-mono text-slate-700">{selectedTask.sessionId}</dd>
                    <dt className="font-semibold text-slate-400">控制模式</dt><dd className="text-slate-700">{selectedTask.controlMode === "owned" ? "OnlineWorker 托管" : "外部客户端"}</dd>
                    <dt className="font-semibold text-slate-400">更新时间</dt><dd className="text-slate-700">{formatRelativeTime(selectedTask.updatedAtEpochMs, nowMs, t)}</dd>
                  </dl>

                  <section className="border-b border-[var(--ow-line-soft)] py-4">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-sm font-bold text-slate-900">会话片段</h3>
                      <span className="text-xs text-slate-400">最近 {TASK_BOARD_DETAIL_TURN_LIMIT} 条</span>
                    </div>
                    {selectedConversationTurns.length > 0 ? (
                      <ol className="mt-3 max-h-72 space-y-2 overflow-y-auto pr-1">
                        {selectedConversationTurns.map((turn, index) => (
                          <li
                            key={`${turn.role}:${turn.timestamp ?? ""}:${index}`}
                            className={`grid grid-cols-[42px_minmax(0,1fr)] gap-3 rounded-md border px-3 py-2 text-sm ${
                              turn.role === "user"
                                ? "border-slate-200 bg-white"
                                : "border-slate-200/80 bg-slate-50"
                            }`}
                          >
                            <span className="pt-0.5 text-xs font-semibold text-slate-500">
                              {turn.role === "user" ? "你" : "Agent"}
                            </span>
                            <p className="line-clamp-3 whitespace-pre-wrap break-words leading-5 text-slate-700">{turn.content}</p>
                          </li>
                        ))}
                      </ol>
                    ) : selectedConversationLoading ? (
                      <p className="mt-3 text-xs text-slate-400">正在读取会话内容…</p>
                    ) : selectedConversationError ? (
                      <p className="mt-3 text-xs text-slate-400">暂时无法读取会话内容。</p>
                    ) : (
                      <p className="mt-3 text-xs text-slate-400">暂无可显示的会话内容。</p>
                    )}
                  </section>

                  <section className="border-b border-[var(--ow-line-soft)] py-4">
                    <h3 className="text-sm font-bold text-slate-900">最近事件</h3>
                    {selectedTask.recentEvents.length > 0 ? (
                      <ol className="mt-3 space-y-3">
                        {selectedTask.recentEvents.map((event, index) => (
                          <li key={`${event.kind}:${event.createdAt}:${index}`} className="flex gap-3 text-xs">
                            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-400" />
                            <div className="min-w-0">
                              <p className="font-semibold text-slate-700">{event.kind}</p>
                              {event.summary ? <p className="mt-0.5 line-clamp-2 text-slate-500">{event.summary}</p> : null}
                            </div>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p className="mt-2 text-xs text-slate-400">暂无更多生命周期事件。</p>
                    )}
                  </section>

                  {selectedTask.mirroredOnly ? (
                    <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">请在原终端处理。</p>
                  ) : selectedTask.controlReason && !selectedTask.canInterrupt && !selectedTask.canRecover ? (
                    <p className="mt-4 text-sm text-slate-500">{selectedTask.controlReason}</p>
                  ) : null}

                  <div className="mt-4 flex flex-wrap items-center gap-2">
                    {isApprovalTask(selectedTask) ? (
                      <>
                        <button type="button" disabled={busyApprovalTaskIdSet.has(selectedTask.id)} onClick={() => handleSingleApprovalAction(selectedTask, "exec_allow")} className="ow-btn-primary h-9 rounded-lg px-4 text-sm font-semibold disabled:opacity-50">{t.taskBoard.approve}</button>
                        <button type="button" disabled={busyApprovalTaskIdSet.has(selectedTask.id)} onClick={() => handleSingleApprovalAction(selectedTask, "exec_deny")} className="ow-btn h-9 rounded-lg px-4 text-sm font-semibold text-rose-700 disabled:opacity-50">{t.taskBoard.deny}</button>
                      </>
                    ) : null}
                    {selectedTask.canRecover ? (
                      <button type="button" disabled={pendingControl?.taskId === selectedTask.id} onClick={() => void handleControlAction(selectedTask, "recover")} className="ow-btn-primary h-9 rounded-lg px-4 text-sm font-semibold disabled:opacity-50">{pendingControl?.taskId === selectedTask.id && pendingControl.action === "recover" ? "正在恢复…" : "恢复"}</button>
                    ) : null}
                    {selectedTask.canContinue ? (
                      <button type="button" onClick={() => handleContinue(selectedTask)} className="ow-btn-primary h-9 rounded-lg px-4 text-sm font-semibold">继续</button>
                    ) : null}
                    {selectedTask.canInterrupt ? (
                      <button type="button" disabled={pendingControl?.taskId === selectedTask.id} onClick={() => void handleControlAction(selectedTask, "interrupt")} className="ow-btn h-9 rounded-lg border border-slate-300 px-4 text-sm font-semibold text-slate-700 disabled:opacity-50">{pendingControl?.taskId === selectedTask.id && pendingControl.action === "interrupt" ? "正在中断…" : "中断"}</button>
                    ) : null}
                    <button type="button" onClick={() => handleOpen(selectedTask)} className="ow-btn h-9 rounded-lg px-4 text-sm font-semibold text-slate-700">打开 Session</button>
                    <button type="button" onClick={() => handleTogglePin(selectedTask)} aria-pressed={selectedTask.pinned} className="ml-auto text-xs font-semibold text-slate-500 hover:text-slate-900">{selectedTask.pinned ? t.taskBoard.unpin : t.taskBoard.pin}</button>
                  </div>
                </div>
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-slate-400">选择一个 Session 查看详情。</div>
              )}
            </aside>
          </div>
        </div>
      )}
    </div>
  );
}
