import { existsSync, readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const allowedVariables = new Set([
  'API_URL',
  'NEXT_PUBLIC_API_URL',
  'NEXT_PUBLIC_SUPABASE_URL',
  'NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY',
]);
const rootEnvPath = fileURLToPath(new URL('../../../.env', import.meta.url));

if (existsSync(rootEnvPath)) {
  for (const line of readFileSync(rootEnvPath, 'utf8').split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
    if (!match || !allowedVariables.has(match[1]) || process.env[match[1]]) continue;
    const value = match[2].replace(/^(?:"([\s\S]*)"|'([\s\S]*)')$/, '$1$2');
    process.env[match[1]] = value;
  }
}

const command = process.argv[2];
if (!['dev', 'build', 'start'].includes(command)) {
  throw new Error('Expected a Next.js command: dev, build, or start.');
}

const nextBin = fileURLToPath(new URL('../node_modules/next/dist/bin/next', import.meta.url));
const child = spawn(process.execPath, [nextBin, command, ...process.argv.slice(3)], {
  env: process.env,
  stdio: 'inherit',
});

child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});
