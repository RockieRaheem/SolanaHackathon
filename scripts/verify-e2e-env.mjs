const mode = process.argv[2];
const missing = [];

const roles = ['OWNER', 'BURSAR', 'CASHIER', 'AUDITOR'];

for (const role of roles) {
  const emailName = `E2E_${role}_EMAIL`;
  const passwordName = `E2E_${role}_PASSWORD`;

  if (!process.env[emailName]?.trim()) missing.push(emailName);
  if (!process.env[passwordName]?.trim()) missing.push(passwordName);
}

if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
  process.env.E2E_SCHOOL_ID?.trim() ?? '',
)) {
  missing.push('E2E_SCHOOL_ID as an exact UUID');
}
if (!process.env.E2E_SCHOOL_MARKER?.startsWith('E2E-')) {
  missing.push('E2E_SCHOOL_MARKER beginning with E2E-');
}

if (mode === 'mutations') {
  if (process.env.E2E_ALLOW_MUTATIONS !== 'true') missing.push('E2E_ALLOW_MUTATIONS=true');
  if (process.env.E2E_ISOLATED_ENVIRONMENT !== 'true') {
    missing.push('E2E_ISOLATED_ENVIRONMENT=true');
  }
}

if (!['auth', 'mutations'].includes(mode)) {
  throw new Error('Usage: node scripts/verify-e2e-env.mjs <auth|mutations>');
}

if (missing.length) {
  console.error(`E2E ${mode} gate refused to run. Configure: ${missing.join(', ')}`);
  process.exit(1);
}

console.log(`E2E ${mode} environment gate passed.`);
