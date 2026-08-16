import type { MenubarPopoverSessionLane } from "../components/menubar-popover/types";

export function formatTokenCount(value: number | null, withUnit = false) {
  if (value === null || Number.isNaN(value)) {
    return "--";
  }
  if (value >= 1_000_000) {
    const formatted = `${(value / 1_000_000).toFixed(1)}M`;
    return withUnit ? `${formatted} tok` : formatted;
  }
  if (value >= 1_000) {
    const formatted = `${(value / 1_000).toFixed(1)}k`;
    return withUnit ? `${formatted} tok` : formatted;
  }
  return withUnit ? `${value} tok` : String(value);
}

export function formatRelativeAge(updatedAtEpoch: number | null, nowMs: number) {
  if (!updatedAtEpoch) {
    return "--";
  }
  const updatedAtMs = updatedAtEpoch < 1_000_000_000_000 ? updatedAtEpoch * 1000 : updatedAtEpoch;
  const deltaSeconds = Math.max(0, Math.floor((nowMs - updatedAtMs) / 1000));
  if (deltaSeconds < 60) {
    return `${deltaSeconds}s ago`;
  }
  const deltaMinutes = Math.floor(deltaSeconds / 60);
  if (deltaMinutes < 60) {
    return `${deltaMinutes}m ago`;
  }
  const deltaHours = Math.floor(deltaMinutes / 60);
  if (deltaHours < 24) {
    return `${deltaHours}h ago`;
  }
  return `${Math.floor(deltaHours / 24)}d ago`;
}

export function providerAccent(providerId: string) {
  const accents = [
    {
      laneDot: "bg-[var(--ow-blue)]",
      laneText: "text-[var(--ow-blue)]",
      cardBorder: "border-[var(--ow-line)]",
      cardBg: "bg-[var(--ow-blue-soft)]",
    },
    {
      laneDot: "bg-[var(--ow-purple)]",
      laneText: "text-[var(--ow-purple)]",
      cardBorder: "border-[var(--ow-line)]",
      cardBg: "bg-[var(--ow-purple-soft)]",
    },
    {
      laneDot: "bg-[var(--ow-green)]",
      laneText: "text-[var(--ow-green)]",
      cardBorder: "border-[var(--ow-line)]",
      cardBg: "bg-[var(--ow-green-soft)]",
    },
    {
      laneDot: "bg-[var(--ow-amber)]",
      laneText: "text-[var(--ow-warning-text)]",
      cardBorder: "border-[var(--ow-line)]",
      cardBg: "bg-[var(--ow-amber-soft)]",
    },
  ];

  if (providerId === "codex") {
    return accents[0];
  }
  if (providerId === "claude") {
    return accents[1];
  }

  const hash = [...providerId].reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return accents[hash % accents.length];
}

export function statusTone(status: string | null) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized.includes("need")) {
    return {
      badge: "border border-[var(--ow-amber-soft)] bg-[var(--ow-amber-soft)] text-[var(--ow-warning-text)]",
      chip: "bg-[var(--ow-amber-soft)] text-[var(--ow-warning-text)]",
      text: "text-[var(--ow-warning-text)]",
    };
  }
  if (normalized.includes("run")) {
    return {
      badge: "border border-[var(--ow-blue-soft)] bg-[var(--ow-blue-soft)] text-[var(--ow-blue)]",
      chip: "bg-[var(--ow-green-soft)] text-[var(--ow-green)]",
      text: "text-[var(--ow-green)]",
    };
  }
  return {
    badge: "border border-[var(--ow-line)] bg-[var(--ow-panel-soft)] text-[var(--ow-muted)]",
    chip: "bg-[var(--ow-panel-soft)] text-[var(--ow-muted)]",
    text: "text-[var(--ow-muted)]",
  };
}

export function lanePreviewText(lane: MenubarPopoverSessionLane) {
  if (lane.latestPreview?.trim()) {
    return lane.latestPreview.trim();
  }
  if (lane.title?.trim()) {
    return lane.title.trim();
  }
  return "No recent message";
}
