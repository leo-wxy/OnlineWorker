import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import test from "node:test";

test("session browser keeps workspace counts, selection and live metadata consistent", {
  skip: process.env.ONLINEWORKER_RUN_UI_TESTS !== "1",
  timeout: 60_000,
}, async () => {
  const { createServer } = await import("vite");
  const { default: react } = await import("@vitejs/plugin-react");
  const { default: puppeteer } = await import("puppeteer");
  const server = await createServer({
    root: fileURLToPath(new URL("../", import.meta.url)),
    configFile: false,
    plugins: [react(), {
      name: "session-regression-page",
      configureServer(server) {
        server.middlewares.use(async (request, response, next) => {
          if (request.url !== "/__session-regression.html") return next();
          try {
            response.setHeader("Content-Type", "text/html");
            response.end(await server.transformIndexHtml(request.url, html));
          } catch (error) {
            next(error);
          }
        });
      },
    }],
    logLevel: "error",
    server: { host: "127.0.0.1", port: 0, hmr: false },
  });
  const html = `<!doctype html><html><body><div id="root"></div>
    <script type="module">
      import React from "react";
      import { createRoot } from "react-dom/client";
      import { I18nProvider } from "/src/i18n/index.tsx";
      import { SessionBrowser } from "/src/pages/SessionBrowser.tsx";
      const root = createRoot(document.getElementById("root"));
      window.renderSessions = (activities = []) => root.render(
        React.createElement(I18nProvider, null,
          React.createElement(SessionBrowser, { taskBoardActivities: activities })),
      );
      window.renderSessions();
    </script></body></html>`;
  let browser;
  const pageErrors = [];
  try {
    await server.listen();
    browser = await puppeteer.launch({ headless: "shell" });
    const page = await browser.newPage();
    page.setDefaultTimeout(5000);
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.evaluateOnNewDocument(() => {
      window.listCalls = [];
      window.readCalls = [];
      window.startCalls = [];
      window.sessionRows = [
        { id: "moved-task", workspace: "/tmp/current-project", title: "Moved task" },
        { id: "other-task", workspace: "/tmp/other-project", title: "Other task" },
        { id: "moved-task", workspace: "/tmp/old-project", title: "Moved task" },
        { id: "archived-task", workspace: "/tmp/archived-project", title: "Archived task", archived: true },
        { id: "archived-other", workspace: "/tmp/other-project", title: "Archived other task", archived: true },
        {
          id: "archived-temp", title: "Archived temporary task", archived: true,
          workspace: "/Users/example/Documents/Codex/2026-08-18/new-chat",
          workspaceGroup: "/Users/example/Documents/Codex", workspaceGroupKind: "temporary",
        },
        ...["2026-08-19", "2026-08-20"].map((day) => ({
          id: `temp-${day}`, title: `Temporary ${day}`,
          workspace: `/Users/example/Documents/Codex/${day}/new-chat`,
          workspaceGroup: "/Users/example/Documents/Codex", workspaceGroupKind: "temporary",
        })),
      ];
      let callbackId = 0;
      window.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener() {} };
      window.__TAURI_INTERNALS__ = {
        transformCallback: () => ++callbackId,
        unregisterCallback() {},
        async invoke(command, args = {}) {
          if (command === "get_provider_metadata") return [{
            id: "codex", label: "Codex", visible: true, managed: true,
            capabilities: { sessions: true },
          }];
          if (command === "get_task_board_state") return { version: 1, pinned: [] };
          if (command === "list_provider_sessions") {
            window.listCalls.push(args);
            return structuredClone(window.sessionRows);
          }
          if (command === "read_provider_session") {
            window.readCalls.push(args);
            return [];
          }
          if (command === "start_provider_session_message") {
            window.startCalls.push(args);
            const session = { id: "temp-new", title: args.text, workspace: args.workspaceDir,
              workspaceGroup: args.workspaceDir, workspaceGroupKind: "temporary" };
            window.sessionRows.push(session);
            return { accepted: true, thread_id: session.id, session };
          }
          if (command.startsWith("plugin:event|")) return 1;
          if (command.endsWith("provider_session_event_stream")) return null;
          throw new Error(`Unexpected native command: ${command}`);
        },
      };
    });
    const address = server.httpServer.address();
    await page.goto(`http://127.0.0.1:${address.port}/__session-regression.html`);
    await page.waitForSelector("h4");
    const workspaceCounts = () => page.evaluate(() => Object.fromEntries(
      [...document.querySelectorAll("button")].flatMap((button) => {
        const path = button.children[1]?.lastElementChild?.textContent;
        return path?.startsWith("/") ? [[path, Number(button.lastElementChild.textContent)]] : [];
      }),
    ));
    assert.deepEqual(await workspaceCounts(), {
      "/tmp/current-project": 1,
      "/tmp/other-project": 1,
      "/Users/example/Documents/Codex": 2,
    }, "Active workspaces must count only visible active sessions");
    await page.evaluate(() => {
      [...document.querySelectorAll("button")]
        .find((button) => button.textContent.includes("/tmp/other-project")).click();
    });
    await page.waitForFunction(() => document.querySelector("h3")?.textContent === "Other task");
    assert.deepEqual(await page.$$eval("h4", (nodes) => nodes.map((node) => node.textContent)), ["Other task"]);
    await page.evaluate(() => document.querySelector("h4").closest('[role="button"]').click());
    assert.equal(await page.$eval("h3", (node) => node.textContent), "Other task");

    await page.evaluate(() => {
      window.sessionRows.push({
        id: "live-task", workspace: "/tmp/other-project", title: "Native task title",
      });
      window.liveActivity = {
        providerId: "codex", sessionId: "live-task", status: "running",
        title: "## Referenced chats with Codex: These are live references to Codex tasks",
        workspacePath: "/tmp/other-project", workspaceId: "codex:/tmp/other-project",
        lastAssistantMessage: "Working", lastEventKind: "message.assistant.delta",
        updatedAt: 1800000000,
      };
      window.renderSessions([window.liveActivity]);
    });
    await page.waitForFunction(() => [...document.querySelectorAll("h4")]
      .some((node) => node.textContent === "Native task title"));
    assert.equal(await page.evaluate(() => window.listCalls.at(-1).forceRefresh), true);
    const refreshCount = await page.evaluate(() => window.listCalls.length);
    await page.evaluate(async () => {
      for (let index = 0; index < 5; index += 1) {
        window.renderSessions([{ ...window.liveActivity, lastAssistantMessage: `Progress ${index}` }]);
        await new Promise(requestAnimationFrame);
      }
    });
    assert.equal(await page.evaluate(() => window.listCalls.length), refreshCount);
    await page.evaluate(() => {
      const groups = [...document.querySelectorAll("button")]
        .filter((button) => button.textContent.includes("/Users/example/Documents/Codex"));
      if (groups.length !== 1 || !/Temporary sessions|临时会话/.test(groups[0].textContent)) {
        throw new Error("Temporary directories were not grouped");
      }
      groups[0].click();
    });
    await page.waitForFunction(() => document.querySelectorAll("h4").length === 2);
    assert.deepEqual(await page.$$eval("h4", (nodes) => nodes.map((node) => node.textContent).sort()),
      ["Temporary 2026-08-19", "Temporary 2026-08-20"]);
    await page.evaluate(() => [...document.querySelectorAll("h4")]
      .find((node) => node.textContent === "Temporary 2026-08-20").closest('[role="button"]').click());
    await page.waitForFunction(() => window.readCalls.at(-1).sessionId === "temp-2026-08-20");
    assert.equal(await page.evaluate(() => window.readCalls.at(-1).workspaceDir),
      "/Users/example/Documents/Codex/2026-08-20/new-chat");
    await page.evaluate(() => [...document.querySelectorAll("button")]
      .find((button) => /New session|新建会话/.test(button.textContent)).click());
    await page.waitForFunction(() => /New session|新建会话/.test(document.querySelector("h3")?.textContent));
    await page.type("textarea", "Synthetic temporary task");
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => window.startCalls.length === 1);
    assert.equal(await page.evaluate(() => window.startCalls[0].workspaceDir), "/Users/example/Documents/Codex");
    await page.waitForFunction(() => document.querySelector("h3")?.textContent === "Synthetic temporary task");

    await page.evaluate(() => [...document.querySelectorAll("button")]
      .find((button) => button.textContent === "Archived").click());
    await page.waitForFunction(() => document.querySelector("h4")?.textContent === "Archived temporary task");
    assert.deepEqual(await workspaceCounts(), {
      "/tmp/archived-project": 1,
      "/tmp/other-project": 1,
      "/Users/example/Documents/Codex": 1,
    }, "Archived workspaces must count only visible archived sessions");
    await page.evaluate(() => [...document.querySelectorAll("button")]
      .find((button) => button.textContent.includes("/tmp/archived-project")).click());
    await page.waitForFunction(() => document.querySelector("h3")?.textContent === "Archived task");
    assert.deepEqual(await page.$$eval("h4", (nodes) => nodes.map((node) => node.textContent)), ["Archived task"]);
    await page.evaluate(() => [...document.querySelectorAll("button")]
      .find((button) => button.textContent === "Active").click());
    await page.waitForFunction(() => [...document.querySelectorAll("h4")]
      .some((node) => node.textContent === "Other task"));
    assert.deepEqual(await workspaceCounts(), {
      "/tmp/current-project": 1,
      "/tmp/other-project": 2,
      "/Users/example/Documents/Codex": 3,
    });
    assert.deepEqual(pageErrors, []);
  } catch (error) {
    if (pageErrors.length) error.message += `\nBrowser errors: ${pageErrors.join("; ")}`;
    throw error;
  } finally {
    await browser?.close();
    await server.close();
  }
});
