import { spawn, execSync, ChildProcess } from 'child_process';
import path from 'path';
import fs from 'fs';

async function isUrlReady(url: string): Promise<boolean> {
  try {
    const res = await fetch(url);
    return res.status < 500;
  } catch {
    return false;
  }
}

async function waitForUrl(url: string, timeoutMs: number = 30000): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await isUrlReady(url)) return;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`Timeout waiting for ${url} after ${timeoutMs}ms`);
}

export default async function globalSetup() {
  const repoRoot = path.resolve(__dirname, '../..');
  const frontendDir = path.resolve(__dirname, '..');
  const stateFilePath = path.resolve(frontendDir, '.e2e-state.json');
  const tempDbPath = path.resolve(repoRoot, 'opsdesk_e2e.db');

  let backendPid: number | undefined;
  let frontendPid: number | undefined;

  // 1. Check or start Backend
  const backendReady = await isUrlReady('http://127.0.0.1:8000/health');
  if (!backendReady) {
    console.log('[E2E Global Setup] Seeding SQLite database at:', tempDbPath);
    const dbUrl = `sqlite:///${tempDbPath.replace(/\\/g, '/')}`;
    execSync('python -m backend.seed.seed_data --reset --yes', {
      cwd: repoRoot,
      env: {
        ...process.env,
        DATABASE_URL: dbUrl,
        AUTH_MODE: 'demo',
        APP_ENV: 'development',
        ALLOW_DEMO_AUTH: 'true',
      },
      stdio: 'inherit',
    });

    console.log('[E2E Global Setup] Starting backend process on port 8000...');
    const backendProcess = spawn(
      'python',
      ['-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8000'],
      {
        cwd: repoRoot,
        env: {
          ...process.env,
          DATABASE_URL: dbUrl,
          AUTH_MODE: 'demo',
          APP_ENV: 'development',
          ALLOW_DEMO_AUTH: 'true',
        },
        stdio: 'inherit',
      }
    );

    backendPid = backendProcess.pid;
    await waitForUrl('http://127.0.0.1:8000/ready', 30000);
    console.log('[E2E Global Setup] Backend is ready!');
  } else {
    console.log('[E2E Global Setup] Connected to existing backend at http://127.0.0.1:8000');
  }

  // 2. Check or start Frontend
  const frontendReady = await isUrlReady('http://127.0.0.1:3000');
  if (!frontendReady) {
    const nextDir = path.resolve(frontendDir, '.next');
    if (!fs.existsSync(nextDir)) {
      console.log('[E2E Global Setup] Building Next.js application...');
      execSync('npm run build', {
        cwd: frontendDir,
        env: {
          ...process.env,
          NEXT_PUBLIC_API_URL: 'http://127.0.0.1:8000',
          NEXT_PUBLIC_AUTH_MODE: 'demo',
        },
        stdio: 'inherit',
      });
    }

    console.log('[E2E Global Setup] Starting Next.js frontend on port 3000...');
    const nextBin = path.resolve(frontendDir, 'node_modules/next/dist/bin/next');
    const frontendProcess = spawn(
      process.execPath,
      [nextBin, 'start', '-p', '3000'],
      {
        cwd: frontendDir,
        env: {
          ...process.env,
          NEXT_PUBLIC_API_URL: 'http://127.0.0.1:8000',
          NEXT_PUBLIC_AUTH_MODE: 'demo',
        },
        stdio: 'inherit',
      }
    );

    frontendPid = frontendProcess.pid;
    await waitForUrl('http://127.0.0.1:3000', 30000);
    console.log('[E2E Global Setup] Frontend is ready!');
  } else {
    console.log('[E2E Global Setup] Connected to existing frontend at http://127.0.0.1:3000');
  }

  // Write state to file for teardown
  fs.writeFileSync(
    stateFilePath,
    JSON.stringify({
      backendPid,
      frontendPid,
      tempDbPath: backendPid ? tempDbPath : undefined,
    }),
    'utf-8'
  );
}
