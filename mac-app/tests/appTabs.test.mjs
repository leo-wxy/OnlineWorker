import test from "node:test";
import assert from "node:assert/strict";

import {
  ALL_APP_TABS,
  PRIMARY_APP_TABS,
  isSupportedAppTab,
} from "../src/utils/appTabs.js";

test("PRIMARY_APP_TABS excludes config from the main navigation", () => {
  assert.deepEqual(PRIMARY_APP_TABS, ["dashboard", "sessions", "usage", "commands", "setup"]);
  assert.equal(PRIMARY_APP_TABS.includes("config"), false);
});

test("ALL_APP_TABS still keeps config as an internal supported route", () => {
  assert.equal(ALL_APP_TABS.includes("config"), true);
  assert.equal(isSupportedAppTab("config"), true);
});

test("isSupportedAppTab only accepts declared tabs", () => {
  assert.equal(isSupportedAppTab("dashboard"), true);
  assert.equal(isSupportedAppTab("sessions"), true);
  assert.equal(isSupportedAppTab("usage"), true);
  assert.equal(isSupportedAppTab("commands"), true);
  assert.equal(isSupportedAppTab("setup"), true);
  assert.equal(isSupportedAppTab("unknown"), false);
});
