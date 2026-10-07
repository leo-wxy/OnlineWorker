import assert from "node:assert/strict";
import test from "node:test";
import { appUpdateBusy, appUpdateProgress, mergeAppUpdateStatus } from "../src/utils/appUpdate.js";

test("an old snapshot cannot override a newer download or install event", () => {
  const ready = { revision: 8, phase: "ready", downloadedBytes: 100, totalBytes: 100 };
  assert.strictEqual(mergeAppUpdateStatus(ready, { revision: 7, phase: "downloading" }), ready);
  assert.equal(mergeAppUpdateStatus(ready, { revision: 9, phase: "installing" }).phase, "installing");
});

test("only active operations disable update actions, so failures can retry", () => {
  for (const phase of ["checking", "downloading", "installing"]) assert.equal(appUpdateBusy({ phase }), true);
  for (const phase of ["idle", "current", "available", "ready"]) assert.equal(appUpdateBusy({ phase }), false);
  assert.equal(appUpdateBusy(null), false);
});

test("download progress supports unknown totals and stays within the bar", () => {
  assert.equal(appUpdateProgress({ downloadedBytes: 50, totalBytes: 100 }), 50);
  assert.equal(appUpdateProgress({ downloadedBytes: 200, totalBytes: 100 }), 100);
  assert.equal(appUpdateProgress({ downloadedBytes: 50, totalBytes: null }), null);
  assert.equal(appUpdateProgress(null), null);
});
