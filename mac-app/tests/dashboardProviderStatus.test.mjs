import test from "node:test";
import assert from "node:assert/strict";

import {
  providerShowsPort,
  providerStatusValue,
} from "../src/utils/dashboardProviderStatus.js";

test("providerShowsPort only returns true for positive ports", () => {
  assert.equal(providerShowsPort({ port: 4722 }), true);
  assert.equal(providerShowsPort({ port: 0 }), false);
  assert.equal(providerShowsPort({ port: null }), false);
  assert.equal(providerShowsPort({}), false);
});

test("providerStatusValue falls back to detail when dynamic port is zero", () => {
  assert.equal(
    providerStatusValue({ port: 0 }, "• codemaker serve：✅ 已连接"),
    "• codemaker serve：✅ 已连接",
  );
  assert.equal(providerStatusValue({ port: 4722 }, "healthy"), 4722);
});
