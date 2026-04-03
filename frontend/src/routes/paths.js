export const APP_ROUTE_PATHS = Object.freeze({
  login: "/",
  upload: "/upload",
  legacyVerify: "/verify/:sessionId",
  generalizedVerify: "/sessions/:sessionId/generalized-verify",
});

export const APP_ROUTE_CATALOG = Object.freeze([
  Object.freeze({ key: "login", path: APP_ROUTE_PATHS.login, protected: false }),
  Object.freeze({ key: "upload", path: APP_ROUTE_PATHS.upload, protected: true }),
  Object.freeze({ key: "legacyVerify", path: APP_ROUTE_PATHS.legacyVerify, protected: true }),
  Object.freeze({ key: "generalizedVerify", path: APP_ROUTE_PATHS.generalizedVerify, protected: true }),
]);

function buildPath(template, replacements) {
  return Object.entries(replacements).reduce((path, [key, value]) => {
    return path.replace(`:${key}`, encodeURIComponent(value));
  }, template);
}

export function getLegacyVerifyPath(sessionId) {
  return buildPath(APP_ROUTE_PATHS.legacyVerify, { sessionId });
}

export function getGeneralizedVerifyPath(sessionId) {
  return buildPath(APP_ROUTE_PATHS.generalizedVerify, { sessionId });
}
