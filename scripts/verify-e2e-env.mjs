const mode = process.argv[2];
const missing = [];

if (!process.env.E2E_BURSAR_EMAIL?.trim()) missing.push('E2E_BURSAR_EMAIL');
if (!process.env.E2E_BURSAR_PASSWORD?.trim()) missing.push('E2E_BURSAR_PASSWORD');

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
