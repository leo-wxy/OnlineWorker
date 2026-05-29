#!/usr/bin/env node

import { createRequire } from "node:module";
import { createServer } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { mkdir, readFile } from "node:fs/promises";
import { spawn } from "node:child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "..");
const macAppDir = join(repoRoot, "mac-app");
const outputDir = join(repoRoot, "docs", "screenshots");
const require = createRequire(join(macAppDir, "package.json"));
const puppeteer = require("puppeteer");

const SCREENSHOTS = [
  { tab: "Dashboard", file: "dashboard.png" },
  { tab: "Setup", file: "setup.png" },
  { tab: "Sessions", file: "sessions-overview.png", afterNavigate: openFirstSessionMenu },
  { tab: "Usage", file: "usage.png" },
  { tab: "AI", file: "ai-services.png" },
  { tab: "AI", file: "ai-scenarios.png", afterNavigate: openAiScenarios },
];

function sleep(ms) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

function freePort(start = 1420) {
  return new Promise((resolvePort, reject) => {
    const tryPort = (port) => {
      const server = createServer();
      server.once("error", () => tryPort(port + 1));
      server.once("listening", () => {
        server.close(() => resolvePort(port));
      });
      server.listen(port, "127.0.0.1");
    };
    try {
      tryPort(start);
    } catch (error) {
      reject(error);
    }
  });
}

function waitForHttp(url, timeoutMs = 30_000) {
  const started = Date.now();
  return new Promise((resolveReady, reject) => {
    const tick = async () => {
      try {
        const response = await fetch(url);
        if (response.ok) {
          resolveReady();
          return;
        }
      } catch {
        // Vite may still be starting.
      }
      if (Date.now() - started > timeoutMs) {
        reject(new Error(`Timed out waiting for ${url}`));
        return;
      }
      setTimeout(tick, 300);
    };
    void tick();
  });
}

function startVite(port) {
  const viteBin = join(macAppDir, "node_modules", "vite", "bin", "vite.js");
  const child = spawn(
    process.execPath,
    [viteBin, "--host", "127.0.0.1", "--port", String(port), "--strictPort"],
    {
      cwd: macAppDir,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, BROWSER: "none" },
    },
  );
  child.stdout.on("data", (chunk) => process.stdout.write(chunk));
  child.stderr.on("data", (chunk) => process.stderr.write(chunk));
  return child;
}

async function appWindowViewport() {
  const configuredWidth = Number(process.env.ONLINEWORKER_SCREENSHOT_WIDTH);
  const configuredHeight = Number(process.env.ONLINEWORKER_SCREENSHOT_HEIGHT);
  if (configuredWidth && configuredHeight) {
    return {
      width: configuredWidth,
      height: configuredHeight,
      deviceScaleFactor: Number(process.env.ONLINEWORKER_SCREENSHOT_SCALE || 1),
    };
  }

  if (process.env.ONLINEWORKER_SCREENSHOT_USE_TAURI_WINDOW === "1") {
    try {
      const configPath = join(macAppDir, "src-tauri", "tauri.conf.json");
      const config = JSON.parse(await readFile(configPath, "utf8"));
      const mainWindow = config.app?.windows?.find((window) => window.label === "main")
        ?? config.app?.windows?.[0]
        ?? {};
      return {
        width: Number(mainWindow.width) || 960,
        height: Number(mainWindow.height) || 700,
        deviceScaleFactor: Number(process.env.ONLINEWORKER_SCREENSHOT_SCALE || 1),
      };
    } catch {
      // Fall through to the stable README viewport.
    }
  }

  return { width: 1920, height: 1200, deviceScaleFactor: 1 };
}

function demoProviders() {
  const baseCapabilities = {
    sessions: true,
    send: true,
    commands: true,
    approvals: true,
    questions: true,
    photos: true,
    files: true,
    usage: true,
    commandWrappers: [],
    controlModes: ["app"],
    messageRewrite: null,
  };
  return [
    {
      id: "codex",
      runtimeId: "codex",
      label: "Codex",
      description: "OpenAI Codex CLI",
      visible: true,
      managed: true,
      autostart: true,
      bin: "codex",
      transport: { owner: "stdio", live: "owner_bridge", type: "stdio", appServerPort: null, appServerUrl: null },
      liveTransport: "owner_bridge",
      controlMode: "app",
      capabilities: baseCapabilities,
      messageHooks: { abusiveLanguageNormalization: { enabled: false, mode: "off" } },
      externalCli: { launcherWrapsClaude: false },
      install: { cliNames: ["codex"] },
      process: { cleanupMatchers: [] },
      icon: null,
    },
    {
      id: "claude",
      runtimeId: "claude",
      label: "Claude",
      description: "Claude Code CLI",
      visible: true,
      managed: true,
      autostart: true,
      bin: "claude",
      transport: { owner: "stdio", live: "stdio", type: "stdio", appServerPort: null, appServerUrl: null },
      liveTransport: "stdio",
      controlMode: "app",
      capabilities: baseCapabilities,
      messageHooks: { abusiveLanguageNormalization: { enabled: false, mode: "off" } },
      externalCli: { launcherWrapsClaude: false },
      install: { cliNames: ["claude"] },
      process: { cleanupMatchers: [] },
      icon: null,
    },
  ];
}

function demoUsage(providerId) {
  const days = [
    ["2026-05-23", 9200, 2100, 0, 2600],
    ["2026-05-24", 12400, 2900, 0, 4100],
    ["2026-05-25", 15100, 3600, 0, 5200],
    ["2026-05-26", 11800, 2500, 0, 3900],
    ["2026-05-27", 8700, 1800, 0, 2100],
    ["2026-05-28", 13400, 3300, 0, 4700],
    ["2026-05-29", 10900, 2700, 0, 3500],
  ].map(([date, inputTokens, outputTokens, cacheCreationTokens, cacheReadTokens]) => ({
    date,
    inputTokens,
    outputTokens,
    cacheCreationTokens,
    cacheReadTokens,
    totalTokens: inputTokens + outputTokens + cacheCreationTokens + cacheReadTokens,
    totalCostUsd: null,
  }));
  return {
    providerId,
    days,
    updatedAtEpoch: Math.floor(Date.now() / 1000),
    unsupportedReason: null,
  };
}

function demoAiConfig() {
  return {
    services: [
      {
        id: "openai_default",
        name: "OpenAI",
        protocol: "openai_compatible_chat",
        baseUrl: "https://api.example.com/v1",
        endpoint: null,
        apiKey: "demo-api-key",
        models: ["demo-model", "demo-fast"],
        defaultModel: "demo-model",
        timeoutSeconds: 20,
        enabled: true,
      },
      {
        id: "claude_default",
        name: "Claude",
        protocol: "claude_messages",
        baseUrl: null,
        endpoint: "https://api.example.com/messages",
        apiKey: "",
        models: ["demo-sonnet", "demo-haiku"],
        defaultModel: "demo-sonnet",
        timeoutSeconds: 20,
        enabled: false,
      },
    ],
    scenarios: [
      {
        id: "notification_summary",
        enabled: true,
        serviceId: "openai_default",
        model: "",
        outputSchema: "notification_summary_v1",
        fallback: "local_notification_summary_rules",
        limits: { preview_title: 16 },
        promptTemplate: [
          "Summarize an OnlineWorker completion notification.",
          "Return JSON with preview_title and summary only.",
          "",
          "Current task:",
          "{{task_summary}}",
          "",
          "Final assistant message:",
          "{{final_message}}",
        ].join("\\n"),
      },
    ],
  };
}

function demoDashboardState() {
  return {
    overall: "healthy",
    bot: { process: "healthy", telegram: "connected", pid: null, lastHeartbeat: null },
    providers: [
      {
        id: "codex",
        label: "codex",
        description: null,
        capabilities: demoProviders()[0].capabilities,
        icon: null,
        managed: true,
        autostart: true,
        health: "healthy",
        port: null,
        detail: "codex app-server: connected",
        transport: "stdio",
        liveTransport: "owner_bridge",
        controlMode: "app",
        bin: "codex",
      },
      {
        id: "claude",
        label: "claude",
        description: null,
        capabilities: demoProviders()[1].capabilities,
        icon: null,
        managed: true,
        autostart: true,
        health: "healthy",
        port: null,
        detail: "claude CLI: connected",
        transport: "stdio",
        liveTransport: "stdio",
        controlMode: "app",
        bin: "claude",
      },
    ],
    alerts: [],
    recentActivity: {
      activeWorkspaceId: "demo-workspace",
      activeWorkspaceName: "demo-workspace",
      activeWorkspacePath: "/demo/workspaces/demo-workspace",
      activeTool: "codex",
      activeSessionId: "demo-session-001",
      activeSessionTool: "codex",
      highlightedThreadPreview: "Update README screenshots",
      activeThreadCount: 3,
    },
    generatedAtEpoch: Math.floor(Date.now() / 1000),
  };
}

function demoCodexThreads() {
  return [
    {
      id: "demo-session-001",
      title: "Update README screenshots",
      cwd: "/demo/workspaces/onlineworker",
      archived: false,
      rollout_path: "/demo/rollouts/demo-session-001.jsonl",
      model_provider: "codex",
      source: "cli",
      is_smoke: false,
    },
    {
      id: "demo-session-002",
      title: "Review usage adapter",
      cwd: "/demo/workspaces/onlineworker",
      archived: false,
      rollout_path: "/demo/rollouts/demo-session-002.jsonl",
      model_provider: "codex",
      source: "vscode",
      is_smoke: false,
    },
    {
      id: "demo-session-003",
      title: "Archive completed task",
      cwd: "/demo/workspaces/desktop-app",
      archived: false,
      rollout_path: "/demo/rollouts/demo-session-003.jsonl",
      model_provider: "codex",
      source: "cli",
      is_smoke: false,
    },
    {
      id: "demo-session-004",
      title: "Plan notification flow",
      cwd: "/demo/workspaces/desktop-app",
      archived: true,
      rollout_path: "/demo/rollouts/demo-session-004.jsonl",
      model_provider: "codex",
      source: "cli",
      is_smoke: false,
    },
  ];
}

function demoTauriScript() {
  const data = {
    providers: demoProviders(),
    dashboard: demoDashboardState(),
    codexThreads: demoCodexThreads(),
    ai: demoAiConfig(),
  };
  return `
(() => {
  const data = ${JSON.stringify(data)};
  let callbackId = 1;
  const callbacks = new Map();
  window.localStorage.setItem("onlineworker.locale", "en");
  window.localStorage.setItem("onlineworker.setup.botfather.completed", "1");
  window.__TAURI_EVENT_PLUGIN_INTERNALS__ = {
    unregisterListener() {},
  };
  window.__TAURI_INTERNALS__ = {
    metadata: {
      currentWindow: { label: "main" },
      currentWebview: { label: "main" },
    },
    callbacks,
    transformCallback(callback, once = false) {
      const id = callbackId++;
      callbacks.set(id, { callback, once });
      return id;
    },
    unregisterCallback(id) {
      callbacks.delete(id);
    },
    runCallback(id, payload) {
      const entry = callbacks.get(id);
      if (!entry) return;
      entry.callback(payload);
      if (entry.once) callbacks.delete(id);
    },
    convertFileSrc(path) {
      return path;
    },
    async invoke(cmd, args = {}) {
      switch (cmd) {
        case "plugin:event|listen":
          return callbackId++;
        case "plugin:event|unlisten":
        case "plugin:event|emit":
        case "plugin:event|emit_to":
          return null;
        case "check_first_run":
          return false;
        case "create_default_config":
        case "write_env_field":
        case "set_provider_flags":
        case "set_ai_config":
        case "service_start":
        case "service_stop":
        case "service_restart":
        case "archive_provider_session":
          return "ok";
        case "service_status":
          return { running: true, pid: null };
        case "get_dashboard_state":
          return data.dashboard;
        case "get_provider_metadata":
          return data.providers;
        case "check_cli":
          return true;
        case "reveal_env_field":
          return args.key === "TELEGRAM_TOKEN" ? "demo-token-value" : "";
        case "read_env_field":
          if (args.key === "ALLOWED_USER_ID") return "123456789";
          if (args.key === "GROUP_CHAT_ID") return "-1001234567890";
          return "";
        case "test_bot_token":
          return { ok: true, username: "demo_bot", bot_id: 1001, first_name: "OnlineWorker Demo" };
        case "test_group_access":
          return { ok: true, title: "Demo Group", chat_type: "supergroup", is_forum: true };
        case "test_bot_permissions":
          return { ok: true, status: "administrator", can_manage_topics: true, can_delete_messages: true, can_pin_messages: true };
        case "list_codex_threads":
          return data.codexThreads;
        case "list_claude_sessions":
          return [
            { id: "claude-demo-001", title: "Review release notes", directory: "/demo/workspaces/onlineworker", archived: false },
            { id: "claude-demo-002", title: "Draft setup guide", directory: "/demo/workspaces/docs", archived: false }
          ];
        case "read_codex_thread_state":
        case "read_codex_thread_updates":
        case "read_provider_session":
        case "read_claude_session":
          return { turns: [], cursor: { offset: 0 }, replace: true };
        case "get_provider_usage_summary":
          return ${demoUsage.toString()}(args.providerId || "codex");
        case "get_ai_config":
          return data.ai;
        case "test_ai_service_connection":
          return { ok: true, status: 200, message: "Connected" };
        case "get_notification_channels":
          return [];
        case "get_command_registry":
          return { commands: [], lastRefreshedEpoch: null, lastPublishedEpoch: null, hasUnpublishedChanges: false };
        case "read_config":
          return { raw: "schema_version: 2\\n", path: "/demo/config.yaml" };
        case "read_env":
        case "read_env_raw":
          return { lines: [], path: "/demo/.env" };
        default:
          console.warn("[readme screenshot mock] unhandled invoke", cmd, args);
          return null;
      }
    },
  };
})();
`;
}

async function clickText(page, text) {
  await page.evaluate((target) => {
    const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
    const button = [...document.querySelectorAll("button")]
      .find((candidate) => normalize(candidate.textContent).includes(target));
    if (!button) {
      throw new Error(`Button not found: ${target}`);
    }
    button.click();
  }, text);
}

async function openFirstSessionMenu(page) {
  await page.waitForFunction(() => document.querySelectorAll('button[aria-label]').length > 0);
  await page.evaluate(() => {
    const button = [...document.querySelectorAll('button[aria-label]')]
      .find((candidate) => /session/i.test(candidate.getAttribute("aria-label") || ""));
    if (!button) {
      throw new Error("Session action button not found");
    }
    button.click();
  });
  await page.waitForSelector('[role="menu"]');
}

async function openAiScenarios(page) {
  await clickText(page, "Scenarios");
  await page.waitForFunction(() => document.body.textContent?.includes("Notification summary"));
}

async function capture(baseUrl) {
  await mkdir(outputDir, { recursive: true });
  const viewport = await appWindowViewport();
  console.log(
    `[screenshots] viewport ${viewport.width}x${viewport.height} @${viewport.deviceScaleFactor}x`,
  );
  const browser = await puppeteer.launch({
    headless: "shell",
    defaultViewport: viewport,
    protocolTimeout: 30_000,
  });

  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(10_000);
    page.setDefaultNavigationTimeout(15_000);
    await page.evaluateOnNewDocument(demoTauriScript());
    console.log(`[screenshots] open ${baseUrl}`);
    await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".ow-app-shell");

    for (const item of SCREENSHOTS) {
      console.log(`[screenshots] capture ${item.file}`);
      await clickText(page, item.tab);
      await sleep(500);
      if (item.afterNavigate) {
        await item.afterNavigate(page);
        await sleep(300);
      }
      await page.screenshot({
        path: join(outputDir, item.file),
        fullPage: false,
        captureBeyondViewport: false,
      });
    }
    console.log("[screenshots] done");
  } finally {
    await browser.close();
  }
}

const port = Number(process.env.ONLINEWORKER_SCREENSHOT_PORT || await freePort());
const baseUrl = process.env.ONLINEWORKER_SCREENSHOT_URL || `http://127.0.0.1:${port}`;
let vite = null;

try {
  if (!process.env.ONLINEWORKER_SCREENSHOT_URL) {
    vite = startVite(port);
    await waitForHttp(baseUrl);
  }
  await capture(baseUrl);
} finally {
  if (vite) {
    vite.kill("SIGTERM");
  }
}
