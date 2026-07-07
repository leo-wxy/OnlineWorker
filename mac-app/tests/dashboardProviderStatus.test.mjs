import test from "node:test";
import assert from "node:assert/strict";

import { providerShowsPort } from "../src/utils/dashboardProviderStatus.js";

test("providerShowsPort only returns true for positive ports", () => {
  assert.equal(providerShowsPort({ port: 4722 }), true);
  assert.equal(providerShowsPort({ port: 0 }), false);
  assert.equal(providerShowsPort({ port: null }), false);
  assert.equal(providerShowsPort({}), false);
});
