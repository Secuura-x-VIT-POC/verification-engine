import assert from "node:assert/strict";
import {
  APP_ROUTE_CATALOG,
  APP_ROUTE_PATHS,
  getGeneralizedVerifyPath,
  getLegacyVerifyPath,
} from "../src/routes/paths.js";

export const checks = [
  {
    name: "route catalog keeps both legacy and generalized verify routes alive",
    run() {
      const paths = APP_ROUTE_CATALOG.map((route) => route.path);

      assert.ok(paths.includes(APP_ROUTE_PATHS.legacyVerify));
      assert.ok(paths.includes(APP_ROUTE_PATHS.generalizedVerify));
    },
  },
  {
    name: "route builders produce session-specific paths",
    run() {
      assert.equal(getLegacyVerifyPath("session-1"), "/verify/session-1");
      assert.equal(
        getGeneralizedVerifyPath("session/with spaces"),
        "/sessions/session%2Fwith%20spaces/generalized-verify"
      );
    },
  },
];
