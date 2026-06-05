import { useCallback, useEffect, useMemo, useState } from "react";
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
}

const DEFAULT_TASK_BOARD_STATE: TaskBoardState = {
  version: 1,
  pinned: [],
};

const PINNED_PREVIEW_HYDRATION_LIMIT = 12;

interface TaskBoardActivityStreamEvent {
  kind: "snapshot" | "activity" | "error";
  activities?: TaskBoardSessionActivity[];
  activity?: TaskBoardSessionActivity | null;
  error?: string | null;
}

interface RefreshOptions {
  includeActivities?: boolean;
}

function taskActivityKey(activity: TaskBoardSessionActivity) {
  return `${activity.providerId}:${activity.sessionId}`;
}

function taskSessionKey(providerId: string, sessionId: string) {
  return `${providerId}:${sessionId}`;
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

async function hydratePinnedSessionPreviews(
  sessions: UnifiedSession[],
  taskBoardState: TaskBoardState,
) {
  const pinnedKeys = new Set(
    taskBoardState.pinned.map((item) => taskSessionKey(item.providerId, item.sessionId)),
  );
  if (pinnedKeys.size === 0) {
    return sessions;
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

  return Promise.all(sessions.map(async (session) => {
    if (!hydrationKeys.has(taskSessionKey(session.type, session.id))) {
      return session;
    }
    try {
      const lastMessage = await readSessionLastMessage(session);
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

function TaskCard({
  task,
  tone,
  nowMs,
  onOpen,
  onTogglePin,
}: {
  task: TaskBoardTask;
  tone: "needsAttention" | "running" | "pinned";
  nowMs: number;
  onOpen: (task: TaskBoardTask) => void;
  onTogglePin: (task: TaskBoardTask) => void;
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
}: {
  title: string;
  count: number;
  empty: string;
  tasks: TaskBoardTask[];
  tone: "needsAttention" | "running" | "pinned";
  nowMs: number;
  onOpen: (task: TaskBoardTask) => void;
  onTogglePin: (task: TaskBoardTask) => void;
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
            />
          ))
        )}
      </div>
    </section>
  );
}

export function TaskBoard({ onOpenSession }: Props) {
  const { t } = useI18n();
  const [providers, setProviders] = useState<ProviderMetadata[]>([]);
  const [dashboardState, setDashboardState] = useState<DashboardState | null>(null);
  const [taskBoardState, setTaskBoardState] = useState<TaskBoardState>(DEFAULT_TASK_BOARD_STATE);
  const [sessionActivities, setSessionActivities] = useState<TaskBoardSessionActivity[]>([]);
  const [sessions, setSessions] = useState<UnifiedSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const providerLabels = useMemo(
    () => Object.fromEntries(
      providers.map((provider) => [provider.id, provider.label || provider.id]),
    ) as Record<string, string>,
    [providers],
  );

  const refresh = useCallback(async ({ includeActivities = true }: RefreshOptions = {}) => {
    setRefreshing(true);
    try {
      const [nextProviders, nextDashboard, nextTaskBoardState] = await Promise.all([
        fetchProviderMetadata(),
        invoke<DashboardState>("get_dashboard_state"),
        invoke<TaskBoardState>("get_task_board_state"),
      ]);
      const nextSessionActivities = includeActivities
        ? await invoke<TaskBoardSessionActivity[]>("get_task_board_session_activities").catch((activityError) => {
          console.warn("Failed to load task board session activity projection", activityError);
          return [];
        })
        : null;
      setProviders(nextProviders);
      setDashboardState(nextDashboard);
      setTaskBoardState(nextTaskBoardState);
      if (nextSessionActivities !== null) {
        setSessionActivities(nextSessionActivities);
      }
      setNowMs(Date.now());
      setError(null);
      setLoading(false);

      const visibleProviders = visibleSessionProviders(nextProviders) as ProviderMetadata[];
      const sessionResults = await Promise.all(
        visibleProviders.map(async (provider) => {
          try {
            if (provider.id === "codex") {
              return (await fetchCodexSessions()).map((session) =>
                toCodexSession(session, t.sessions.workspaceFallback),
              );
            }
            if (provider.id === "claude") {
              return (await fetchClaudeSessions()).map((session) =>
                toClaudeSession(session, t.sessions.workspaceFallback),
              );
            }
            return normalizeGenericProviderSessions(
              provider.id,
              await fetchProviderSessions(provider.id),
              t.sessions.workspaceFallback,
            );
          } catch (sessionError) {
            console.warn(`Failed to load task board sessions for ${provider.id}`, sessionError);
            return [];
          }
        }),
      );

      setSessions(await hydratePinnedSessionPreviews(sessionResults.flat(), nextTaskBoardState));
      setNowMs(Date.now());
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [t.sessions.workspaceFallback]);

  useEffect(() => {
    void refresh({ includeActivities: true });
  }, [refresh]);

  useEffect(() => {
    const channel = new Channel<TaskBoardActivityStreamEvent>();
    let activeStreamId: number | null = null;
    let disposed = false;
    channel.onmessage = (event) => {
      if (event.kind === "snapshot") {
        setSessionActivities(event.activities ?? []);
        setNowMs(Date.now());
        setLoading(false);
        return;
      }
      if (event.kind === "activity" && event.activity) {
        const activity = event.activity;
        setSessionActivities((current) => upsertSessionActivity(current, activity));
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
  }, []);

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
      sessionActivities,
      dashboardState,
      taskBoardState,
      providerLabels,
      nowEpochMs: nowMs,
    }),
    [dashboardState, nowMs, providerLabels, sessionActivities, sessions, taskBoardState],
  );

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
            />
          </div>
        </div>
      )}
    </div>
  );
}
