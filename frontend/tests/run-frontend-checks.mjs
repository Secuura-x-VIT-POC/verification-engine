import { checks as generalizedVerificationChecks } from "./generalizedVerificationModels.test.mjs";
import { checks as routeChecks } from "./routes.test.mjs";

const checks = [...generalizedVerificationChecks, ...routeChecks];
let failures = 0;

for (const check of checks) {
  try {
    await check.run();
    console.log(`ok - ${check.name}`);
  } catch (error) {
    failures += 1;
    console.error(`not ok - ${check.name}`);
    console.error(error?.stack || error);
  }
}

if (failures) {
  console.error(`${failures} frontend checks failed.`);
  process.exit(1);
}

console.log(`All ${checks.length} frontend checks passed.`);
