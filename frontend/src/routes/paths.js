export const APP_ROUTE_PATHS = Object.freeze({
  login: "/",
  upload: "/upload",
  verify: "/verify/:sessionId",
});

export const APP_ROUTE_CATALOG = Object.freeze([
  Object.freeze({ key: "login", path: APP_ROUTE_PATHS.login, protected: false }),
  Object.freeze({ key: "upload", path: APP_ROUTE_PATHS.upload, protected: true }),
  Object.freeze({ key: "verify", path: APP_ROUTE_PATHS.verify, protected: true }),
]);

function buildPath(template, replacements) {
  return Object.entries(replacements).reduce((path, [key, value]) => {
    return path.replace(`:${key}`, encodeURIComponent(value));
  }, template);
}

export function getVerifyPath(sessionId) {
  return buildPath(APP_ROUTE_PATHS.verify, { sessionId });
}
