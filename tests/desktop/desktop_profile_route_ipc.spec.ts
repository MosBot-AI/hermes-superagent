/** Overlay in the pinned Hermes apps/desktop/e2e/core directory. */
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { setTimeout as delay } from 'node:timers/promises'

import { expect, type ElectronApplication, type Page, test } from '@playwright/test'

import {
  type CoreSandbox,
  coreAppEnv,
  createCoreSandbox,
  freePort,
  launchCoreApp,
  REPO_ROOT,
  sandboxProcesses,
  writeProviderHome
} from './harness'
import { startScriptedProvider } from './provider'

const profile = 'scout'
const title = 'Bot Chat'
const remoteId = 'spare'
const python = process.env.HERMES_E2E_PYTHON

interface Route {
  connectionId: string
  mode: 'local' | 'remote'
  primary?: true
  profile: string
  targetProfile: string
}

interface RouteDial {
  connectionId: string
  profile: string
}

interface DesktopBridge {
  getProfileRoutes(profiles: string[]): Promise<Route[]>
  getConnectionFor(dial: RouteDial): Promise<{
    baseUrl: string
    mode: string
    connectionId: string
    registryScoped: boolean
  }>
  getGatewayWsUrlFor(dial: RouteDial): Promise<{ ok: boolean; wsUrl?: string; error?: string }>
  connections: {
    remove(id: string): Promise<{ ok: boolean }>
  }
}

interface RuntimeSDK {
  host: {
    profileRoutes(): Promise<Route[]>
    requestProfile(
      route: Route,
      method: string,
      params: Record<string, unknown>,
      timeoutMs?: number,
      options?: { spawnPriority: 'foreground' }
    ): Promise<{ sessions: { id: string; resolved_id: string }[] }>
    retainProfileSocket(route: Route): () => void
  }
}

declare global {
  interface Window {
    __E07_ROUTE_PROBE__?: RuntimeSDK['host']
    __E07_RELEASE_ROUTE__?: () => void
  }
}

interface Gateway {
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

function privateEnv(box: CoreSandbox): Record<string, string> {
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

function runPython(env: Record<string, string>, code: string, ...args: string[]): string {
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

function seedInstall(
  box: CoreSandbox,
  env: Record<string, string>,
  modelUrl: string,
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

function startGateway(box: CoreSandbox, env: Record<string, string>): Gateway {
  const log = fs.openSync(path.join(box.root, 'gateway.log'), 'w', 0o600)
  try {
    const child = spawn(python!, ['-m', 'gateway.run'], {
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

function readEndpoint(gateway: Gateway): ReadyEndpoint | null {
  const output = runPython(
    gateway.env,
    `
import json
from pathlib import Path
from hermes_cli.gateway_runtime import discover_gateway_endpoint
from hermes_cli.gateway_runtime_discovery import query_identify
from hermes_constants import get_hermes_home
root = get_hermes_home()
home = Path(root) / "profiles" / "scout"
observation = discover_gateway_endpoint(home, timeout=1)
if observation.state != "ready":
    print("null")
else:
    endpoint = observation.endpoint
    identity = query_identify(Path(root), timeout=1)
    print(json.dumps({"origin": endpoint.api_origin, "instanceId": endpoint.instance_id,
                      "profileId": endpoint.profile_id, "pid": identity["pid"]}))
`
  )

  return JSON.parse(output) as ReadyEndpoint | null
}

async function waitForEndpoint(gateway: Gateway): Promise<ReadyEndpoint> {
  let endpoint: ReadyEndpoint | null = null
  await expect
    .poll(
      () => {
        expect(gateway.child.exitCode, 'owned Gateway is still running').toBeNull()
        endpoint = readEndpoint(gateway)

        return endpoint?.pid
      },
      { timeout: 45_000, intervals: [250, 500, 1_000] }
    )
    .toBe(gateway.child.pid)
  expect(endpoint!.profileId).toBe(path.join(gateway.box.hermesHome, 'profiles', profile))
  expect(endpoint!.origin).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/)

  return endpoint!
}

async function stopGateway(gateway: Gateway): Promise<void> {
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

function recordRequests(page: Page) {
  const sockets: { port: string; profile: string | null; closed: boolean }[] = []
  const frames: { port: string; method: string; profile?: string; title?: string; limit?: number }[] = []
  page.on('websocket', socket => {
    const url = new URL(socket.url())
    if (url.pathname !== '/api/ws') {
      return
    }
    // Keep only the destination and profile. URLs can contain synthetic credentials.
    const route = { port: url.port, profile: url.searchParams.get('profile'), closed: false }
    sockets.push(route)
    socket.on('close', () => {
      route.closed = true
    })
    socket.on('framesent', event => {
      try {
        const frame = JSON.parse(String(event.payload))
        if (typeof frame?.method === 'string') {
          const { profile: target, title, limit } = frame.params ?? {}
          frames.push({ port: route.port, method: frame.method, profile: target, title, limit })
        }
      } catch {
        // Non-JSON WebSocket data is not an RPC frame.
      }
    })
  })

  return { sockets, frames }
}

function readChats(box: CoreSandbox) {
  return [box.hermesHome, path.join(box.hermesHome, 'profiles', profile)].map(home => {
    const db = new DatabaseSync(path.join(home, 'state.db'), { readOnly: true })
    try {
      return {
        sessions: db.prepare('SELECT id, title, hidden FROM sessions WHERE title = ? ORDER BY id').all(title),
        messages: db
          .prepare(
            'SELECT m.session_id, m.role, m.content FROM messages m JOIN sessions s ON s.id = m.session_id ' +
              'WHERE s.title = ? ORDER BY m.id'
          )
          .all(title)
      }
    } finally {
      db.close()
    }
  })
}

function requestChat(page: Page, route: Route, limit: number) {
  return page.evaluate(
    async ({ route, limit, title }) => {
      try {
        const result = await window.__E07_ROUTE_PROBE__!.requestProfile(
          route,
          'session.list',
          {
            profile: route.targetProfile,
            title,
            include_hidden: true,
            limit
          },
          12_000,
          { spawnPriority: 'foreground' }
        )

        return { ids: result.sessions.map(row => [row.id, row.resolved_id]) }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)

        // The only error text exposed to Playwright is a known sanitized verdict.
        return { refused: /No connection with id "spare"\./.test(message) ? 'removed' : 'unexpected' }
      }
    },
    { route, limit, title }
  )
}

test('real Desktop IPC routes same-name Bot Chats and refuses a removed source', async () => {
  test.setTimeout(200_000)
  expect(process.platform).toBe('linux')
  expect(path.isAbsolute(python ?? ''), 'an absolute pinned interpreter is required').toBe(true)
  expect(process.env.HERMES_E2E_CORE_ROOT, 'an isolated core root is required').toBeTruthy()

  const provider = await startScriptedProvider()
  const localBox = createCoreSandbox('a')
  const remoteBox = createCoreSandbox('b')
  const gateways: Gateway[] = []
  let app: ElectronApplication | undefined
  let completed = false
  try {
    const localEnv = privateEnv(localBox)
    const remoteEnv = privateEnv(remoteBox)
    const remotePort = await freePort()
    seedInstall(localBox, localEnv, provider.url, 'local', '1'.repeat(32))
    seedInstall(remoteBox, remoteEnv, provider.url, 'spare', '2'.repeat(32), remotePort)
    for (const box of [localBox, remoteBox]) {
      expect(Buffer.byteLength(path.join(box.hermesHome, 'gateway.sock'))).toBeLessThan(104)
    }
    const pluginDir = path.join(localBox.hermesHome, 'desktop-plugins', 'e07-route-probe')
    fs.mkdirSync(pluginDir, { recursive: true })
    fs.writeFileSync(
      path.join(pluginDir, 'plugin.js'),
      `
import { host } from '@hermes/plugin-sdk'
export default {
  id: 'e07-route-probe',
  register() { globalThis.__E07_ROUTE_PROBE__ = host }
}
`
    )

    const local = startGateway(localBox, localEnv)
    gateways.push(local)
    const remote = startGateway(remoteBox, remoteEnv)
    gateways.push(remote)
    const [localEndpoint, remoteEndpoint] = await Promise.all([waitForEndpoint(local), waitForEndpoint(remote)])
    expect(localEndpoint.instanceId).not.toBe(remoteEndpoint.instanceId)
    expect(remoteEndpoint.origin).toBe(`http://127.0.0.1:${remotePort}`)
    expect(localEndpoint.origin).not.toBe(remoteEndpoint.origin)
    const localPort = new URL(localEndpoint.origin).port
    const token = fs.readFileSync(path.join(remoteBox.hermesHome, 'webapp', 'session-token'), 'utf8').trim()
    expect(/^[A-Za-z0-9_-]{43}$/.test(token), 'native test Webapp token is available').toBe(true)
    fs.writeFileSync(
      path.join(localBox.userDataDir, 'connections.json'),
      JSON.stringify({
        version: 2,
        primary: 'local',
        launchMode: 'primary',
        lastUsed: 'local',
        connections: [
          { id: 'local', kind: 'local', label: 'This device' },
          {
            id: remoteId,
            kind: 'remote',
            label: 'Spare',
            url: remoteEndpoint.origin,
            authMode: 'token',
            token: { encoding: 'plain', value: token }
          }
        ]
      }),
      { mode: 0o600 }
    )

    const live = await launchCoreApp(localEnv)
    app = live.app
    const { page } = live
    const wire = recordRequests(page)
    await page.waitForFunction(() => typeof window.__E07_ROUTE_PROBE__?.requestProfile === 'function', undefined, {
      timeout: 45_000
    })
    const expected: Route[] = [
      { connectionId: 'local', mode: 'local', primary: true, profile, targetProfile: profile },
      { connectionId: remoteId, mode: 'remote', profile, targetProfile: profile }
    ]
    const routes = await page.evaluate(
      async ({ profile }) => {
        const bridge = (window as unknown as { hermesDesktop: DesktopBridge }).hermesDesktop
        const named = (routes: Route[]) =>
          routes
            .filter(route => route.profile === profile)
            .sort((left, right) => left.connectionId.localeCompare(right.connectionId))

        return {
          preload: named(await bridge.getProfileRoutes([])),
          sdk: named(await window.__E07_ROUTE_PROBE__!.profileRoutes())
        }
      },
      { profile }
    )
    expect(routes.preload).toEqual(expected)
    expect(routes.sdk).toEqual(expected)
    const [localRoute, remoteRoute] = routes.sdk
    const main = await page.evaluate(async routes => {
      const bridge = (window as unknown as { hermesDesktop: DesktopBridge }).hermesDesktop

      return Promise.all(
        routes.map(async ({ connectionId, profile }) => {
          const descriptor = await bridge.getConnectionFor({ connectionId, profile })
          return [descriptor.connectionId, descriptor.mode, descriptor.baseUrl, descriptor.registryScoped]
        })
      )
    }, routes.sdk)
    expect(main).toEqual([
      ['local', 'local', localEndpoint.origin, true],
      [remoteId, 'remote', remoteEndpoint.origin, true]
    ])

    await page.evaluate(route => {
      window.__E07_RELEASE_ROUTE__ = window.__E07_ROUTE_PROBE__!.retainProfileSocket(route)
    }, remoteRoute!)
    expect(await requestChat(page, localRoute!, 17)).toEqual({ ids: [['fixture-local-scout', 'fixture-local-scout']] })
    expect(await requestChat(page, remoteRoute!, 18)).toEqual({ ids: [['fixture-spare-scout', 'fixture-spare-scout']] })
    const scopedFrames = (limit: number) =>
      wire.frames.filter(frame => frame.method === 'session.list' && frame.title === title && frame.limit === limit)
    expect(scopedFrames(17)).toEqual([{ port: localPort, method: 'session.list', profile, title, limit: 17 }])
    expect(scopedFrames(18)).toEqual([{ port: String(remotePort), method: 'session.list', profile, title, limit: 18 }])
    const remoteSocket = wire.sockets.find(
      socket => socket.port === String(remotePort) && socket.profile === profile && !socket.closed
    )
    expect(remoteSocket, 'the named remote route has an open socket before removal').toBeDefined()
    const chats = [readChats(localBox), readChats(remoteBox)]
    expect(chats).toEqual(
      ['local', 'spare'].map(source =>
        ['default', profile].map(name => {
          const id = `fixture-${source}-${name}`
          return {
            sessions: [{ id, title, hidden: 1 }],
            messages: [{ session_id: id, role: 'user', content: id }]
          }
        })
      )
    )

    const removed = await page.evaluate(async id => {
      const bridge = (window as unknown as { hermesDesktop: DesktopBridge }).hermesDesktop
      return (await bridge.connections.remove(id)).ok
    }, remoteId)
    expect(removed).toBe(true)
    await expect.poll(() => remoteSocket!.closed).toBe(true)
    expect(readEndpoint(remote)).toEqual(remoteEndpoint)
    const remoteHealth = await fetch(`${remoteEndpoint.origin}/api/status`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(5_000)
    })
    expect(remoteHealth.ok, 'the removed listener is independently reachable').toBe(true)
    await remoteHealth.body?.cancel()
    const refusals = await page.evaluate(
      async ({ remoteId, profile }) => {
        const bridge = (window as unknown as { hermesDesktop: DesktopBridge }).hermesDesktop
        const dial = { connectionId: remoteId, profile }
        const missing = await bridge.getConnectionFor({ ...dial, connectionId: '' }).then(
          () => false,
          error => /No connection with id ""\./.test(String(error))
        )
        const stale = await bridge.getGatewayWsUrlFor(dial)
        const remaining = (await bridge.getProfileRoutes([])).filter(route => route.profile === profile)

        return {
          missing,
          stale: stale.ok === false && stale.error === `No connection with id "${remoteId}".` && !stale.wsUrl,
          remaining
        }
      },
      { remoteId, profile }
    )
    expect(refusals).toEqual({ missing: true, stale: true, remaining: [localRoute] })
    expect(await requestChat(page, remoteRoute!, 19)).toEqual({ refused: 'removed' })
    expect(await requestChat(page, localRoute!, 20)).toEqual({ ids: [['fixture-local-scout', 'fixture-local-scout']] })
    expect(scopedFrames(19), 'the removed-route canary never reaches any socket').toEqual([])
    expect(scopedFrames(20)).toEqual([{ port: localPort, method: 'session.list', profile, title, limit: 20 }])
    expect([readChats(localBox), readChats(remoteBox)]).toEqual(chats)
    expect(readEndpoint(local)).toEqual(localEndpoint)
    expect(provider.completions.length).toBe(0)
    await page.evaluate(() => {
      window.__E07_RELEASE_ROUTE__?.()
      delete window.__E07_RELEASE_ROUTE__
    })
    completed = true
  } finally {
    await app?.close().catch(() => undefined)
    const stopped = await Promise.allSettled(gateways.map(stopGateway))
    await provider.close()
    const live = [localBox, remoteBox].flatMap(sandboxProcesses)
    localBox.cleanup()
    remoteBox.cleanup()
    if (completed) {
      expect(
        stopped.every(result => result.status === 'fulfilled'),
        'both owned Gateways stop'
      ).toBe(true)
      expect(live.length, 'no fixture processes remain after teardown').toBe(0)
    }
  }
})
