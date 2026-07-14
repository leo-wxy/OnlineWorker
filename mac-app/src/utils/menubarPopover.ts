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
      laneBorder: "border-[rgba(37,99,235,0.18)]",
      laneDot: "bg-[var(--ow-blue)]",
      laneText: "text-[var(--ow-blue)]",
      laneHint: "text-[rgba(37,99,235,0.7)]",
      tileBg: "bg-[var(--ow-blue-soft)]",
      tileText: "text-[var(--ow-blue)]",
      tileValue: "text-[var(--ow-text)]",
      cardBorder: "border-[rgba(37,99,235,0.16)]",
      cardBg: "bg-[rgba(37,99,235,0.052)]",
      actionText: "text-[var(--ow-blue)]",
      avatarBg: "bg-[var(--ow-blue-soft)]",
    },
    {
      laneBorder: "border-[rgba(124,58,237,0.18)]",
      laneDot: "bg-[var(--ow-purple)]",
      laneText: "text-[var(--ow-purple)]",
      laneHint: "text-[rgba(124,58,237,0.7)]",
      tileBg: "bg-[var(--ow-purple-soft)]",
      tileText: "text-[var(--ow-purple)]",
      tileValue: "text-[var(--ow-text)]",
      cardBorder: "border-[rgba(124,58,237,0.16)]",
      cardBg: "bg-[rgba(124,58,237,0.055)]",
      actionText: "text-[var(--ow-purple)]",
      avatarBg: "bg-[var(--ow-purple-soft)]",
    },
    {
      laneBorder: "border-[rgba(5,150,105,0.18)]",
      laneDot: "bg-[var(--ow-green)]",
      laneText: "text-[var(--ow-green)]",
      laneHint: "text-[rgba(5,150,105,0.72)]",
      tileBg: "bg-[var(--ow-green-soft)]",
      tileText: "text-[var(--ow-green)]",
      tileValue: "text-[var(--ow-text)]",
      cardBorder: "border-[rgba(5,150,105,0.16)]",
      cardBg: "bg-[rgba(5,150,105,0.052)]",
      actionText: "text-[var(--ow-green)]",
      avatarBg: "bg-[var(--ow-green-soft)]",
    },
    {
      laneBorder: "border-[rgba(217,119,6,0.18)]",
      laneDot: "bg-[var(--ow-amber)]",
      laneText: "text-[var(--ow-amber)]",
      laneHint: "text-[rgba(217,119,6,0.72)]",
      tileBg: "bg-[var(--ow-amber-soft)]",
      tileText: "text-[var(--ow-amber)]",
      tileValue: "text-[var(--ow-text)]",
      cardBorder: "border-[rgba(217,119,6,0.16)]",
      cardBg: "bg-[rgba(217,119,6,0.052)]",
      actionText: "text-[var(--ow-amber)]",
      avatarBg: "bg-[var(--ow-amber-soft)]",
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
      badge: "bg-amber-50 text-amber-700 border border-amber-100",
      chip: "bg-amber-50 text-amber-700",
    };
  }
  if (normalized.includes("run")) {
    return {
      badge: "bg-blue-50 text-blue-700 border border-blue-100",
      chip: "bg-emerald-50 text-emerald-700",
    };
  }
  return {
    badge: "bg-slate-100 text-slate-700 border border-slate-200",
    chip: "bg-slate-100 text-slate-700",
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
