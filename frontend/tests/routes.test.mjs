import assert from "node:assert/strict";
import {
	APP_ROUTE_CATALOG,
	APP_ROUTE_PATHS,
	getVerifyPath,
} from "../src/routes/paths.js";

export const checks = [
	{
		name: "route catalog keeps one generalized verify route alive",
		run() {
			const paths = APP_ROUTE_CATALOG.map((route) => route.path);
			const keys = APP_ROUTE_CATALOG.map((route) => route.key);

			assert.ok(paths.includes(APP_ROUTE_PATHS.login));
			assert.ok(paths.includes(APP_ROUTE_PATHS.upload));
			assert.ok(paths.includes(APP_ROUTE_PATHS.verify));

			assert.ok(keys.includes("login"));
			assert.ok(keys.includes("upload"));
			assert.ok(keys.includes("verify"));

			assert.equal(APP_ROUTE_PATHS.verify, "/verify/:sessionId");
			assert.equal(keys.includes("legacyVerify"), false);
			assert.equal(keys.includes("generalizedVerify"), false);
		},
	},
	{
		name: "verify route builder produces session-specific paths",
		run() {
			assert.equal(getVerifyPath("session-1"), "/verify/session-1");
			assert.equal(
				getVerifyPath("session/with spaces"),
				"/verify/session%2Fwith%20spaces"
			);
		},
	},
];