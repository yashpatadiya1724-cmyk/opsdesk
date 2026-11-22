import { execSync } from 'child_process';
import path from 'path';
import fs from 'fs';

function killProcess(pid?: number) {
  if (!pid) return;
  try {
    if (process.platform === 'win32') {
      execSync(`taskkill /PID ${pid} /T /F`, { stdio: 'ignore' });
    } else {
      process.kill(pid, 'SIGTERM');
      setTimeout(() => {
        try {
          process.kill(pid, 'SIGKILL');
        } catch {
          // ignore
        }
      }, 1000);
    }
  } catch {
    // Process might have already exited
  }
}

export default async function globalTeardown() {
  const frontendDir = path.resolve(__dirname, '..');
  const stateFilePath = path.resolve(frontendDir, '.e2e-state.json');

  if (!fs.existsSync(stateFilePath)) return;

  try {
    const raw = fs.readFileSync(stateFilePath, 'utf-8');
    const state = JSON.parse(raw);

    if (state.frontendPid) {
      console.log('[E2E Global Teardown] Terminating frontend process (PID:', state.frontendPid, ')');
      killProcess(state.frontendPid);
    }
    if (state.backendPid) {
      console.log('[E2E Global Teardown] Terminating backend process (PID:', state.backendPid, ')');
      killProcess(state.backendPid);
    }
    if (state.tempDbPath) {
      setTimeout(() => {
        try {
          if (fs.existsSync(state.tempDbPath)) fs.unlinkSync(state.tempDbPath);
          const wal = `${state.tempDbPath}-wal`;
          const shm = `${state.tempDbPath}-shm`;
          if (fs.existsSync(wal)) fs.unlinkSync(wal);
          if (fs.existsSync(shm)) fs.unlinkSync(shm);
        } catch {
          // ignore
        }
      }, 1000);
    }
  } catch (err) {
    console.error('[E2E Global Teardown] Error during teardown:', err);
  } finally {
    try {
      if (fs.existsSync(stateFilePath)) fs.unlinkSync(stateFilePath);
    } catch {
      // ignore
    }
  }
}
