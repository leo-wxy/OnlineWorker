import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { createSingleFlightByKey } from "../src/utils/singleFlight.js";

test("single-flight coalesces concurrent provider loads and releases the key afterwards", async () => {
  const coordinator = createSingleFlightByKey();
  let calls = 0;
  let releaseFirst;
  const firstGate = new Promise((resolve) => {
    releaseFirst = resolve;
  });

  const first = coordinator.run("claude", async () => {
    calls += 1;
    await firstGate;
    return "first";
  });
  const duplicate = coordinator.run("claude", async () => {
    calls += 1;
    return "duplicate";
  });

  assert.equal(calls, 1);
  releaseFirst();
  assert.equal(await first, "first");
  assert.equal(await duplicate, "first");
  assert.equal(calls, 1);

  const next = await coordinator.run("claude", async () => {
    calls += 1;
    return "next";
  });
  assert.equal(next, "next");
  assert.equal(calls, 2);
});

test("SessionBrowser routes provider list IPC through the provider single-flight", () => {
  const source = readFileSync(
    join(import.meta.dirname, "..", "src", "pages", "SessionBrowser.tsx"),
    "utf8",
  );

  assert.match(source, /providerLoadFlightsRef = useRef\(createSingleFlightByKey<ProviderFilter>\(\)\)/);
  assert.match(
    source,
    /providerLoadFlightsRef\.current\.run\(\s*provider,\s*\(\) => fetchProviderSessions\(provider,/s,
  );
});
