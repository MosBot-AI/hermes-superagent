/** Process and profile setup shared by the pinned Electron acceptance cases. */
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'

import { expect } from '@playwright/test'

import { type CoreSandbox, coreAppEnv, REPO_ROOT, writeProviderHome } from './harness'

const python = process.env.HERMES_E2E_PYTHON

export interface Gateway {
  child: ChildProcess
  exited: Promise<number | null>
  box: CoreSandbox
  env: Record<string, string>
}

interface ReadyEndpoint {
  origin: string
  instanceId: string
  profileId: string
  pid: number
}

export function privateEnv(box: CoreSandbox): Record<string, string> {
  fs.chmodSync(box.home, 0o700)
  fs.chmodSync(box.hermesHome, 0o700)
  const dirs = ['runtime', 'cache', 'config', 'data', 'state', 'scratch', 'bundled'].map(name =>
    path.join(box.root, name)
  )
  for (const dir of dirs) {
    fs.mkdirSync(dir, { mode: 0o700 })
  }
  const [runtime, cache, config, data, state, scratch, bundled] = dirs
  const env = coreAppEnv(box, {
    USERPROFILE: box.home,
    HERMES_RUNTIME_DIR: runtime!,
    XDG_RUNTIME_DIR: runtime!,
    XDG_CACHE_HOME: cache!,
    XDG_CONFIG_HOME: config!,
    XDG_DATA_HOME: data!,
    XDG_STATE_HOME: state!,
    TMPDIR: scratch!,
    TMP: scratch!,
    TEMP: scratch!,
    HERMES_BUNDLED_PLUGINS: bundled!,
    HERMES_ENABLE_PROJECT_PLUGINS: '0',
    PYTHONDONTWRITEBYTECODE: '1',
    PYTHONNOUSERSITE: '1'
  })
  const allowed = new Set([
    'PATH',
    'LANG',
    'LC_ALL',
    'TZ',
    'DISPLAY',
    'XAUTHORITY',
    'DBUS_SESSION_BUS_ADDRESS',
    'DBUS_SYSTEM_BUS_ADDRESS',
    'XDG_RUNTIME_DIR',
    'XDG_CACHE_HOME',
    'XDG_CONFIG_HOME',
    'XDG_DATA_HOME',
    'XDG_STATE_HOME',
    'HOME',
    'USERPROFILE',
    'TMPDIR',
    'TMP',
    'TEMP',
    'PYTHONDONTWRITEBYTECODE',
    'PYTHONNOUSERSITE',
    'GIT_NO_LAZY_FETCH'
  ])

  return Object.fromEntries(Object.entries(env).filter(([name]) => allowed.has(name) || name.startsWith('HERMES_')))
}

export function runPython(env: Record<string, string>, code: string, ...args: string[]): string {
  const result = spawnSync(python!, ['-c', code, ...args], {
    cwd: REPO_ROOT,
    env,
    encoding: 'utf8',
    timeout: 10_000
  })
  // Never print subprocess stderr or args into the test report.
  expect(result.status, 'pinned fixture Python command succeeded').toBe(0)

  return result.stdout.trim()
}

export function seedInstall(
  box: CoreSandbox,
  env: Record<string, string>,
  modelUrl: string,
  profile: string,
  label: string,
  installId: string,
  webappPort?: number
) {
  const config = 'telemetry:\n  shared_metrics:\n    enabled: false\nplatform_toolsets:\n  gui: []\n'
  const webapp = webappPort
    ? `webapp:\n  enabled: true\n  host: 127.0.0.1\n  port: ${webappPort}\n`
    : 'webapp:\n  enabled: false\n'
  const namedHome = path.join(box.hermesHome, 'profiles', profile)
  writeProviderHome(box.hermesHome, modelUrl, config + webapp)
  writeProviderHome(namedHome, modelUrl, config)
  fs.chmodSync(namedHome, 0o700)
  fs.writeFileSync(path.join(box.hermesHome, 'install_id'), `${installId}\n`, { mode: 0o600 })
  for (const [home, suffix] of [
    [box.hermesHome, 'default'],
    [namedHome, profile]
  ]) {
    const id = `fixture-${label}-${suffix}`
    fs.writeFileSync(
      path.join(home!, 'models_dev_cache.json'),
      '{"hermes-test-offline":{"id":"hermes-test-offline","env":[],"models":{}}}'
    )
    runPython(
      env,
      `
import sys
from pathlib import Path
from hermes_state import SessionDB
home, session_id = sys.argv[1:]
with SessionDB(Path(home) / "state.db") as db:
    db.create_session(session_id, source="cli", model="mock-model", cwd=home)
    assert db.set_session_title(session_id, "Bot Chat")
    assert db.set_session_hidden(session_id, True)
    db.append_message(session_id, "user", session_id)
`,
      home!,
      id
    )
  }
}

export function configureSavedWebapp(
  local: CoreSandbox,
  remote: CoreSandbox,
  origin: string,
  source: string,
  profile: string
) {
  const token = fs.readFileSync(path.join(remote.hermesHome, 'webapp', 'session-token'), 'utf8').trim()
  expect(/^[A-Za-z0-9_-]{43}$/.test(token), 'native test Webapp token is available').toBe(true)
  fs.writeFileSync(
    path.join(local.userDataDir, 'connections.json'),
    JSON.stringify({
      version: 2,
      primary: source,
      launchMode: 'primary',
      lastUsed: source,
      connections: [
        { id: 'local', kind: 'local', label: 'This device' },
        {
          id: source,
          kind: 'remote',
          label: 'Spare',
          url: origin,
          authMode: 'token',
          token: { encoding: 'plain', value: token }
        }
      ]
    }),
    { mode: 0o600 }
  )
  fs.writeFileSync(
    path.join(local.userDataDir, 'active-profile.json'),
    JSON.stringify({ profile, connectionProfiles: { [source]: profile } }),
    { mode: 0o600 }
  )
}

export function startGateway(box: CoreSandbox, env: Record<string, string>, args = ['-m', 'gateway.run']): Gateway {
  const log = fs.openSync(path.join(box.root, 'gateway.log'), 'w', 0o600)
  try {
    const child = spawn(python!, args, {
      cwd: REPO_ROOT,
      env,
      stdio: ['ignore', log, log]
    })
    const exited = new Promise<number | null>(resolve => {
      child.once('close', resolve)
      child.once('error', () => resolve(null))
    })

    return { child, exited, box, env }
  } finally {
    fs.closeSync(log)
  }
}

export function readEndpoint(gateway: Gateway, profile: string): ReadyEndpoint | null {
  const output = runPython(
    gateway.env,
    `
import json
from pathlib import Path
import sys
from hermes_cli.gateway_runtime import discover_gateway_endpoint
from hermes_cli.gateway_runtime_discovery import query_identify
from hermes_constants import get_hermes_home
root = get_hermes_home()
home = Path(root) / "profiles" / sys.argv[1]
observation = discover_gateway_endpoint(home, timeout=1)
if observation.state != "ready":
    print("null")
else:
    endpoint = observation.endpoint
    identity = query_identify(Path(root), timeout=1)
    print(json.dumps({"origin": endpoint.api_origin, "instanceId": endpoint.instance_id,
                      "profileId": endpoint.profile_id, "pid": identity["pid"]}))
`,
    profile
  )

  return JSON.parse(output) as ReadyEndpoint | null
}

export async function waitForEndpoint(gateway: Gateway, profile: string): Promise<ReadyEndpoint> {
  let endpoint: ReadyEndpoint | null = null
  await expect
    .poll(
      () => {
        expect(gateway.child.exitCode, 'owned Gateway is still running').toBeNull()
        endpoint = readEndpoint(gateway, profile)

        return endpoint?.pid
      },
      { timeout: 45_000, intervals: [250, 500, 1_000] }
    )
    .toBe(gateway.child.pid)
  expect(endpoint!.profileId).toBe(path.join(gateway.box.hermesHome, 'profiles', profile))
  expect(endpoint!.origin).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/)

  return endpoint!
}

export async function stopGateway(gateway: Gateway): Promise<void> {
  const { child, exited, env } = gateway
  if (child.pid !== undefined && child.exitCode === null && child.signalCode === null) {
    try {
      runPython(
        env,
        `
import sys
from gateway.status import write_planned_stop_marker
assert write_planned_stop_marker(int(sys.argv[1]))
`,
        String(child.pid)
      )
      const status = await Promise.race([exited, delay(20_000, 'timeout', { ref: false })])
      expect(status, 'the test-owned Gateway honors planned stop').toBe(0)
    } finally {
      if (child.exitCode === null && child.signalCode === null) {
        child.kill('SIGKILL')
        await Promise.race([exited, delay(5_000, null, { ref: false })])
      }
    }
  }
}
