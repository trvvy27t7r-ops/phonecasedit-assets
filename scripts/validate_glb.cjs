const fs = require('fs');
const path = require('path');
const validator = require('gltf-validator');

const input = process.argv[2];
const output = process.argv[3];
if (!input || !output) {
  throw new Error('Usage: node validate_glb.cjs INPUT.glb REPORT.json');
}

validator.validateBytes(new Uint8Array(fs.readFileSync(input)), {
  uri: path.basename(input),
  maxIssues: 200,
  ignoredIssues: [],
}).then((report) => {
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(report, null, 2));
  const errors = report.issues?.numErrors || 0;
  const warnings = report.issues?.numWarnings || 0;
  console.log(`glTF Validator: ${errors} errors, ${warnings} warnings`);
  if (errors > 0) process.exit(1);
}).catch((error) => {
  console.error(error);
  process.exit(1);
});
