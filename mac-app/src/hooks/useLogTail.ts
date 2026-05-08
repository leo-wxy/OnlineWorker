import { useState, useEffect, useRef, useCallback } from "react";
import { invoke, Channel } from "@tauri-apps/api/core";
import type { LogLine } from "../types";

const MAX_LOG_LINES = 1000;

function parseLogLevel(raw: string): LogLine["level"] {
  if (raw.includes(" DEBUG ") || raw.includes("[DEBUG]")) return "DEBUG";
  if (raw.includes(" INFO ") || raw.includes("[INFO]")) return "INFO";
  if (raw.includes(" WARNING ") || raw.includes("[WARNING]")) return "WARNING";
  if (raw.includes(" ERROR ") || raw.includes("[ERROR]")) return "ERROR";
  return "UNKNOWN";
}

function parseLogLine(raw: string): LogLine {
  const level = parseLogLevel(raw);
  // Python logging format: "2026-03-30 12:34:56,789 - module - LEVEL - message"
  const match = raw.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})[,\d]* - .* - \w+ - (.*)$/);
  return {
    raw,
    level,
    timestamp: match?.[1],
    message: match?.[2] ?? raw,
  };
}

interface UseLogTailReturn {
  lines: LogLine[];
  running: boolean;
  start: () => void;
  stop: () => void;
  clear: () => void;
}

export function useLogTail(): UseLogTailReturn {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [running, setRunning] = useState(false);
  const channelRef = useRef<Channel<string> | null>(null);

  const stop = useCallback(async () => {
    setRunning(false);
    await invoke("stop_log_tail").catch(console.error);
    channelRef.current = null;
  }, []);

  const start = useCallback(async () => {
    if (running) return;
    setRunning(true);

    const channel = new Channel<string>();
    channelRef.current = channel;

    channel.onmessage = (rawLine: string) => {
      setLines((prev) => {
        const newLine = parseLogLine(rawLine);
        const updated = [...prev, newLine];
        // Keep only last MAX_LOG_LINES lines
        return updated.length > MAX_LOG_LINES
          ? updated.slice(updated.length - MAX_LOG_LINES)
          : updated;
      });
    };

    await invoke("start_log_tail", { channel }).catch((err) => {
      console.error("Log tail error:", err);
      setRunning(false);
    });
  }, [running]);

  const clear = useCallback(() => setLines([]), []);

  // Stop on unmount
  useEffect(() => {
    return () => {
      invoke("stop_log_tail").catch(console.error);
    };
  }, []);

  return { lines, running, start, stop, clear };
}
