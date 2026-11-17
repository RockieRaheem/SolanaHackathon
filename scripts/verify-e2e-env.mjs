const mode = process.argv[2];
const missing = [];

const roles = ['OWNER', 'BURSAR', 'CASHIER', 'AUDITOR'];

for (const role of roles) {
  const emailName = `E2E_${role}_EMAIL`;
  const passwordName = `E2E_${role}_PASSWORD`;

  if (!process.env[emailName]?.trim()) missing.push(emailName);
  if (!process.env[passwordName]?.trim()) missing.push(passwordName);
}

if (mode === 'mutations') {
  if (process.env.E2E_ALLOW_MUTATIONS !== 'true') missing.push('E2E_ALLOW_MUTATIONS=true');
  if (process.env.E2E_ISOLATED_ENVIRONMENT !== 'true') {
    missing.push('E2E_ISOLATED_ENVIRONMENT=true');
  }
  if (!process.env.E2E_SCHOOL_MARKER?.startsWith('E2E-')) {
    missing.push('E2E_SCHOOL_MARKER beginning with E2E-');
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
