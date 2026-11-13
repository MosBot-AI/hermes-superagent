/** Overlay in the pinned Hermes apps/desktop/e2e/core directory. */
import { spawn, spawnSync } from 'node:child_process'
import { once } from 'node:events'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'

import { expect, type ElectronApplication, type Page, test } from '@playwright/test'

import { launchBotDesktop } from './desktop_bot_appimage'
import {
  focus,
  installCanonicalObserver,
  lookup,
  observeWire,
  storedChats,
  type WireFrame,
  type WireSocket
} from './desktop_bot_canonical_observer'
import { privateEnv, seedInstall, startGateway, stopGateway, waitForEndpoint } from './desktop_native_gateway_fixture'
import { appLogTail, composer, type CoreSandbox, createCoreSandbox, freePort, REPO_ROOT, sandboxProcesses } from './harness'
import { listProcesses } from './process-census'
import { startScriptedProvider } from './provider'

const profile = 'scout'
const connectionId = 'fixture-ssh'
const canonical = 'fixture-ssh-scout'
const editedProfile = 'harbor'
const decoys = ['fixture-ssh-default', 'fixture-local-default', 'fixture-local-scout']

function shellQuote(value: string) {
  return "'" + value.replaceAll("'", "'\\''") + "'"
}

interface ProfileRoute {
  connectionId: string
  mode: 'local' | 'remote'
  profile: string
  targetProfile: string
}

interface RouteProbe {
  profileRoutes(): Promise<ProfileRoute[]>
  retainProfileSocket(route: ProfileRoute): () => void
  requestProfile(
    route: ProfileRoute,
    method: string,
    params: Record<string, unknown>,
    timeoutMs: number,
    options: { spawnPriority: 'foreground' }
  ): Promise<{ sessions: { id: string; resolved_id: string }[] }>
}

declare global {
  interface Window {
    __E07_SSH_ROUTE_PROBE__?: RouteProbe
    __E07_SSH_RELEASE__?: () => void
  }
}

function installRouteProbe(home: string) {
  const plugin = path.join(home, 'desktop-plugins', 'e07-ssh-route-probe')
  fs.mkdirSync(plugin, { recursive: true })
  fs.writeFileSync(
    path.join(plugin, 'plugin.js'),
    `
import { host } from '@hermes/plugin-sdk'
export default {
  id: 'e07-ssh-route-probe',
  register() { globalThis.__E07_SSH_ROUTE_PROBE__ = host }
}
`
  )
}

async function sshRoute(page: Page, routeProfile: string) {
  await page.waitForFunction(() => typeof window.__E07_SSH_ROUTE_PROBE__?.profileRoutes === 'function')
  return page.evaluate(
    async ({ connectionId, routeProfile }) => {
      const routes = await window.__E07_SSH_ROUTE_PROBE__!.profileRoutes()
      return routes.find(route => route.connectionId === connectionId && route.profile === routeProfile)
    },
    { connectionId, routeProfile }
  )
}

async function readSshChat(page: Page, routeProfile: string, retainSocket: boolean) {
  const route = await sshRoute(page, routeProfile)
  expect(route).toEqual({ connectionId, mode: 'remote', profile: routeProfile, targetProfile: profile })
  expect(await readExactChat(page, route!, 17, retainSocket)).toEqual([[canonical, canonical]])
  return route!
}

interface SshEdit {
  remoteProfile: string
  host?: string
  keyPath?: string
  remoteHermesPath?: string
}

function saveSshConnection(page: Page, edit: SshEdit) {
  return page.evaluate(async ({ connectionId, edit }) => {
    const desktop = (window as unknown as {
      hermesDesktop: {
        connections: {
          save(input: {
            id: string
            kind: 'ssh'
            label: string
          } & SshEdit): Promise<{ ok: boolean; connection: { id: string; remoteProfile: string; port: number } }>
        }
      }
    }).hermesDesktop
    const result = await desktop.connections.save({
      id: connectionId,
      kind: 'ssh',
      label: 'Fixture SSH',
      ...edit
    })
    const { id, remoteProfile, port } = result.connection
    return { ok: result.ok, id, remoteProfile, port }
  }, { connectionId, edit })
}

function testSavedSshConnection(page: Page) {
  return page.evaluate(async id => {
    const desktop = (window as unknown as {
      hermesDesktop: {
        connections: {
          test(id: string): Promise<{ reachable: boolean; sshError?: string }>
        }
      }
    }).hermesDesktop
    const result = await desktop.connections.test(id)
    return { reachable: result.reachable, sshError: result.sshError }
  }, connectionId)
}

function readExactChat(page: Page, route: ProfileRoute, limit: number, retainSocket = false) {
  return page.evaluate(
    async ({ route, limit, retainSocket }) => {
      const sdk = window.__E07_SSH_ROUTE_PROBE__!
      if (retainSocket) window.__E07_SSH_RELEASE__ = sdk.retainProfileSocket(route)
      const result = await sdk.requestProfile(
        route,
        'session.list',
        { title: 'Bot Chat', profile: route.targetProfile, include_hidden: true, limit },
        25_000,
        { spawnPriority: 'foreground' }
      )
      return result.sessions.map(({ id, resolved_id }) => [id, resolved_id])
    },
    { route, limit, retainSocket }
  )
}

function stopSshSessions(listenerPid: number) {
  // OpenSSH session processes can have their own session IDs. Walk only the
  // fixture listener's descendants in the private PID namespace.
  const processes = listProcesses()
  const descendants = new Set([listenerPid])
  for (let previousSize = 0; descendants.size !== previousSize; ) {
    previousSize = descendants.size
    for (const { pid, ppid } of processes) {
      if (pid > 1 && descendants.has(ppid)) descendants.add(pid)
    }
  }
  for (const pid of [...descendants].reverse()) {
    try {
      process.kill(pid, 'SIGTERM')
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error
    }
  }
}

function createSshKey(key: string, env: Record<string, string>) {
  expect(
    spawnSync('ssh-keygen', ['-q', '-t', 'ed25519', '-N', '', '-f', key], {
      env,
      stdio: 'ignore'
    }).status
  ).toBe(0)
}

async function prepareSshServer(
  state: string,
  sshConfig: string,
  python: string,
  localEnv: Record<string, string>,
  remote: CoreSandbox,
  remoteEnv: Record<string, string>
) {
  fs.mkdirSync(state, { mode: 0o700 })
  const port = await freePort()
  const sshUser = os.userInfo().username
  const hostKey = path.join(state, 'host')
  const clientKey = path.join(state, 'key')
  createSshKey(hostKey, localEnv)
  createSshKey(clientKey, localEnv)
  const authorized = path.join(sshConfig, `authorized_keys_${port}`)
  fs.writeFileSync(authorized, fs.readFileSync(clientKey + '.pub'), { mode: 0o600 })
  const knownHosts = path.join(sshConfig, 'known_hosts')
  const hostEntry = (key: string) => `[127.0.0.1]:${port} ${fs.readFileSync(key + '.pub', 'utf8')}`
  fs.appendFileSync(knownHosts, hostEntry(hostKey), { mode: 0o600 })
  const remoteLauncher = path.join(remote.bin, 'hermes')
  fs.writeFileSync(
    remoteLauncher,
    `#!/bin/sh\ncd ${shellQuote(REPO_ROOT)}\nexec ${shellQuote(python)} -m hermes_cli.main "$@"\n`,
    { mode: 0o700 }
  )
  const remoteCommand = path.join(state, 'remote-command')
  const remoteSettings = {
    HOME: remote.home,
    HERMES_HOME: remote.hermesHome,
    HERMES_RUNTIME_DIR: remoteEnv.HERMES_RUNTIME_DIR!,
    PATH: remoteEnv.PATH!,
    LANG: 'C.UTF-8',
    PYTHONDONTWRITEBYTECODE: '1',
    HERMES_ENABLE_PROJECT_PLUGINS: '0'
  }
  fs.writeFileSync(
    remoteCommand,
    `#!/bin/sh\nexec /usr/bin/env -i ${Object.entries(remoteSettings)
      .map(([key, value]) => shellQuote(`${key}=${value}`))
      .join(' ')} /bin/sh -c "$SSH_ORIGINAL_COMMAND"\n`,
    { mode: 0o700 }
  )
  const config = path.join(state, 'sshd.conf')
  const log = path.join(state, 'sshd.log')
  fs.writeFileSync(
    config,
    [
      'ListenAddress 127.0.0.1',
      `Port ${port}`,
      `HostKey ${hostKey}`,
      `AuthorizedKeysFile ${authorized}`,
      'UsePAM no',
      'PasswordAuthentication no',
      'KbdInteractiveAuthentication no',
      'StrictModes yes',
      `PidFile ${state}/sshd.pid`,
      `AllowUsers ${sshUser}`,
      'PermitUserRC no',
      'AllowAgentForwarding no',
      'X11Forwarding no',
      'AllowTcpForwarding local',
      'PermitOpen 127.0.0.1:*',
      'LogLevel VERBOSE',
      `ForceCommand ${remoteCommand}`,
      ''
    ].join('\n'),
    { mode: 0o600 }
  )
  let listener: ReturnType<typeof spawn> | undefined
  const sshLog = () => fs.existsSync(log) ? fs.readFileSync(log, 'utf8') : ''
  const startServer = async () => {
    const before = sshLog().length
    listener = spawn('/usr/sbin/sshd', ['-D', '-E', log, '-f', config], {
      env: localEnv,
      stdio: 'ignore'
    })
    await expect.poll(() => sshLog().slice(before).includes('Server listening')).toBe(true)
  }
  const acceptedKeys = () => sshLog().match(/Accepted publickey/g)?.length ?? 0
  const verifyLogin = () => {
    const loginsBefore = acceptedKeys()
    const login = spawnSync(
      'ssh',
      [
        '-o',
        'BatchMode=yes',
        '-o',
        'IdentitiesOnly=yes',
        '-o',
        'StrictHostKeyChecking=yes',
        '-i',
        clientKey,
        '-p',
        String(port),
        `${sshUser}@127.0.0.1`,
        'printf "%s" "$HERMES_HOME"'
      ],
      { env: localEnv, encoding: 'utf8', timeout: 10_000 }
    )
    if (login.status !== 0) {
      fs.writeFileSync(path.join(state, 'login.log'), login.stderr ?? '', { mode: 0o600 })
    }
    expect(login.status, 'ephemeral OpenSSH key and host key accepted').toBe(0)
    expect(login.stdout).toBe(remote.hermesHome)
    expect(acceptedKeys()).toBe(loginsBefore + 1)
  }

  return {
    port,
    sshUser,
    clientKey,
    remoteLauncher,
    startServer,
    verifyLogin,
    acceptedKeys,
    prepareHostKeyRotation() {
      const replacement = path.join(state, 'rotated-host')
      createSshKey(replacement, localEnv)
      const previousEntry = hostEntry(hostKey)
      const nextEntry = hostEntry(replacement)
      const previousPins = fs.readFileSync(knownHosts, 'utf8')
      const previousConfig = fs.readFileSync(config, 'utf8')
      expect(previousPins).toContain(previousEntry)
      expect(nextEntry).not.toBe(previousEntry)
      fs.writeFileSync(config, previousConfig.replace(`HostKey ${hostKey}\n`, `HostKey ${replacement}\n`))
      return {
        assertOriginalPin: () => expect(fs.readFileSync(knownHosts, 'utf8')).toBe(previousPins),
        installReplacementPin() {
          const staged = knownHosts + '.new'
          fs.writeFileSync(staged, previousPins.replace(previousEntry, nextEntry), { mode: 0o600, flag: 'wx' })
          fs.renameSync(staged, knownHosts)
        }
      }
    },
    listener: () => listener
  }
}

async function verifySshBotChat(routeProfile: string, transition?: 'reconnect' | 'edit' | 'replace' | 'rotate') {
  const rotate = transition === 'rotate'
  const reconnect = transition === 'reconnect' || rotate
  const edit = transition === 'edit'
  const replace = transition === 'replace'
  const expectedProfile = edit ? editedProfile : profile
  const expectedChat = replace ? 'fixture-replacement-scout' : edit ? `fixture-ssh-${editedProfile}` : canonical
  const aliased = routeProfile !== profile
  expect(process.platform).toBe('linux')
  const state = process.env.HERMES_E2E_SSH_STATE
  const python = process.env.HERMES_E2E_PYTHON
  expect(path.isAbsolute(state ?? '') && path.isAbsolute(python ?? '')).toBe(true)
  const provider = await startScriptedProvider()
  const local = createCoreSandbox('a')
  const remote = createCoreSandbox('b')
  const successor = replace ? createCoreSandbox('c') : undefined
  const boxes = successor ? [local, remote, successor] : [local, remote]
  let gateway: ReturnType<typeof startGateway> | undefined
  const servers: Awaited<ReturnType<typeof prepareSshServer>>[] = []
  let app: ElectronApplication | undefined
  let completed = false
  try {
    const localEnv = privateEnv(local)
    const remoteEnv = privateEnv(remote)
    const successorEnv = successor && privateEnv(successor)
    seedInstall(local, localEnv, provider.url, profile, 'local', '1'.repeat(32))
    seedInstall(remote, remoteEnv, provider.url, edit ? [profile, editedProfile] : profile, 'ssh', '2'.repeat(32))
    if (successor) seedInstall(successor, successorEnv!, provider.url, profile, 'replacement', '3'.repeat(32))
    const initial = () => [
      ...boxes.flatMap(box => storedChats(box.hermesHome, profile)),
      ...(edit ? [storedChats(remote.hermesHome, editedProfile)[1]] : [])
    ]
    const sshConfig = path.join(state!, 'account', '.ssh')
    fs.writeFileSync(
      path.join(sshConfig, 'config'),
      `Host 127.0.0.1\n  UserKnownHostsFile ${path.join(sshConfig, 'known_hosts')}\n  IdentitiesOnly yes\n`,
      { mode: 0o600 }
    )
    const original = await prepareSshServer(path.join(state!, 'original'), sshConfig, python!, localEnv, remote, remoteEnv)
    servers.push(original)
    await original.startServer()
    original.verifyLogin()
    const replacement = successor && await prepareSshServer(
      path.join(state!, 'replacement'), sshConfig, python!, localEnv, successor, successorEnv!
    )
    if (replacement) {
      expect(replacement.port).not.toBe(original.port)
      servers.push(replacement)
      await replacement.startServer()
      replacement.verifyLogin()
    }

    installCanonicalObserver(local.hermesHome)
    if (aliased || reconnect) installRouteProbe(local.hermesHome)
    gateway = startGateway(local, localEnv)
    const localEndpoint = await waitForEndpoint(gateway, profile)
    const before = initial()
    fs.writeFileSync(
      path.join(local.userDataDir, 'connections.json'),
      JSON.stringify({
        version: 2,
        primary: 'local',
        connections: [
          { id: 'local', kind: 'local', label: 'This device' },
          {
            id: connectionId,
            kind: 'ssh',
            label: 'Fixture SSH',
            host: '127.0.0.1',
            user: original.sshUser,
            port: original.port,
            keyPath: original.clientKey,
            remoteHermesPath: original.remoteLauncher,
            ...(aliased ? { remoteProfile: profile } : {})
          }
        ]
      }),
      { mode: 0o600 }
    )
    const live = await launchBotDesktop(localEnv)
    app = live.app
    const { page } = live
    const sockets = new Map<WireFrame, WireSocket>()
    const wire = observeWire(page, sockets)
    await expect(composer(page)).toBeVisible({ timeout: 45_000 })
    const localPort = new URL(localEndpoint.origin).port
    let sdkRead: WireFrame | undefined
    let originalRoute: ProfileRoute | undefined
    if (aliased || reconnect) {
      const from = wire.length
      originalRoute = await readSshChat(page, routeProfile, Boolean(transition))
      const reads = wire.slice(from).filter(frame => lookup(frame) && frame.limit === 17)
      expect(reads).toHaveLength(1)
      sdkRead = reads[0]!
      expect(sdkRead).toMatchObject({ profile, includeHidden: true, reply: {} })
      expect(sdkRead.port).not.toBe(localPort)
    }
    await page
      .getByRole('button', { name: 'Bots', exact: true })
      .or(page.getByRole('tab', { name: 'Bots', exact: true }))
      .first()
      .click()
    const roster = page.locator('[data-slot="bots-roster"]')
    const row = roster.locator(`[data-roster-key="${connectionId}::${routeProfile}"]`)
    await expect(row).toBeVisible({ timeout: 45_000 })
    await expect(roster.locator(`[data-roster-key="local::${routeProfile}"]`)).toBeVisible()
    let loginsBeforeRecovery = 0
    if (reconnect) {
      const socket = sockets.get(sdkRead!)!
      expect(socket.closed).toBe(false)
      expect(original.acceptedKeys()).toBeGreaterThan(1)
      const offlineFrom = wire.length
      const focusedBefore = await focus(page)
      const listener = original.listener()!
      const stopped = once(listener, 'exit')
      stopSshSessions(listener.pid!)
      await stopped
      await expect.poll(() => socket.closed).toBe(true)
      await page.evaluate(() => window.__E07_SSH_RELEASE__?.())
      const rotation = rotate ? original.prepareHostKeyRotation() : undefined
      const loginsBeforeRefusal = original.acceptedKeys()
      if (rotation) await original.startServer()
      await row.click()
      const refusal = page.getByRole('alert').filter({ hasText: /Could not open .*’s chat/ })
      await expect(refusal).toContainText('Try again.', { timeout: 45_000 })
      expect(await focus(page)).toEqual(focusedBefore)
      const offlineOperations = wire.slice(offlineFrom).filter(
        frame => lookup(frame) ||
          ['session.create', 'session.resume', 'session.activate', 'prompt.submit'].includes(frame.method)
      )
      expect(offlineOperations).toEqual([])
      expect(initial()).toEqual(before)
      await refusal.getByRole('button', { name: 'Dismiss notification', exact: true }).click()
      if (rotation) {
        expect(await testSavedSshConnection(page)).toEqual({ reachable: false, sshError: 'host-key-changed' })
        expect(original.acceptedKeys()).toBe(loginsBeforeRefusal)
        rotation.assertOriginalPin()
        rotation.installReplacementPin()
      } else {
        await original.startServer()
      }
      loginsBeforeRecovery = original.acceptedKeys()
    }
    if (edit || replacement) {
      const socket = sockets.get(sdkRead!)!
      expect(socket.closed).toBe(false)
      const endpoint = replacement && {
        host: `${replacement.sshUser}@127.0.0.1:${replacement.port}`,
        keyPath: replacement.clientKey,
        remoteHermesPath: replacement.remoteLauncher
      }
      expect(await saveSshConnection(page, { remoteProfile: expectedProfile, ...endpoint })).toEqual({
        ok: true,
        id: connectionId,
        remoteProfile: expectedProfile,
        port: replacement?.port ?? original.port
      })
      await expect.poll(() => socket.closed).toBe(true)
      await page.evaluate(() => window.__E07_SSH_RELEASE__?.())
      await expect.poll(() => sshRoute(page, routeProfile)).toEqual({
        connectionId,
        mode: 'remote',
        profile: routeProfile,
        targetProfile: expectedProfile
      })
    }
    const from = wire.length
    await row.click()
    const viewport = page.locator('[data-slot="aui_thread-viewport"]').filter({ visible: true }).first()
    await expect(viewport.getByText(expectedChat, { exact: true })).toBeVisible({ timeout: 55_000 })
    await expect.poll(() => focus(page)).toEqual({ id: expectedChat, owner: { connectionId, profile: routeProfile } })
    const excluded = edit || replace ? [...decoys, canonical] : decoys
    if (replace) excluded.push('fixture-replacement-default')
    for (const decoy of excluded) {
      await expect(viewport.getByText(decoy, { exact: true })).toHaveCount(0)
    }
    const frames = wire.slice(from)
    const reads = frames.filter(lookup)
    expect(reads).toHaveLength(1)
    expect(reads[0]).toMatchObject({ method: 'session.list', profile: expectedProfile, includeHidden: true, reply: {} })
    expect(reads[0]!.port).not.toBe(localPort)
    if (aliased && !transition) expect(reads[0]!.port).toBe(sdkRead!.port)
    if (transition) expect(reads[0]!.port).not.toBe(sdkRead!.port)
    if (reconnect) expect(original.acceptedKeys()).toBeGreaterThan(loginsBeforeRecovery)
    const opens = frames.filter((frame) => ['session.resume', 'session.activate'].includes(frame.method))
    expect(opens.some((frame) => frame.method === 'session.resume')).toBe(true)
    for (const frame of opens) {
      expect(frame).toMatchObject({ port: reads[0]!.port, profile: expectedProfile, sessionId: expectedChat })
    }
    expect(frames.filter((frame) => ['session.create', 'prompt.submit'].includes(frame.method))).toEqual([])
    if (edit || replacement) {
      const replayFrom = wire.length
      // The captured descriptor still resolves through the saved connection ID.
      const replayChat = replacement ? expectedChat : canonical
      expect(await readExactChat(page, originalRoute!, 18)).toEqual([[replayChat, replayChat]])
      const replayFrames = wire.slice(replayFrom)
      const staleReads = replayFrames.filter(frame => lookup(frame) && frame.limit === 18)
      expect(staleReads).toHaveLength(1)
      expect(staleReads[0]).toMatchObject({
        profile,
        port: reads[0]!.port,
        includeHidden: true,
        reply: {}
      })
      expect(replayFrames.filter(frame =>
        ['session.create', 'session.resume', 'session.activate', 'prompt.submit'].includes(frame.method)
      )).toEqual([])
      expect(await focus(page)).toEqual({ id: expectedChat, owner: { connectionId, profile: routeProfile } })
    }
    expect(initial()).toEqual(before)
    expect(provider.completions.length).toBe(0)
    expect(original.acceptedKeys()).toBeGreaterThan(1)
    if (replacement) {
      expect(replacement.acceptedKeys()).toBeGreaterThan(1)
      original.verifyLogin()
    }
    completed = true
  } catch (error) {
    if (app) fs.writeFileSync(path.join(state!, 'desktop.log'), appLogTail(app), { mode: 0o600 })
    throw error
  } finally {
    await app?.close().catch(() => undefined)
    try {
      if (gateway) await stopGateway(gateway)
    } finally {
      for (const server of servers) server.listener()?.kill()
      await provider.close()
      try {
        if (completed) {
          // The SSH watchdog's last bounded sleep can briefly outlive its shell.
          await expect.poll(() => boxes.flatMap(sandboxProcesses), { timeout: 20_000 }).toEqual([])
        }
      } finally {
        for (const box of boxes) box.cleanup()
      }
    }
  }
}

test('Bot Mode opens the named canonical chat over OpenSSH', async () => {
  test.setTimeout(180_000)
  await verifySshBotChat(profile)
})

test('Bot Mode opens the canonical chat behind an OpenSSH profile alias', async () => {
  test.setTimeout(180_000)
  await verifySshBotChat('default')
})

test('Bot Mode refuses an offline OpenSSH route and reopens the original chat', async () => {
  test.setTimeout(180_000)
  await verifySshBotChat(profile, 'reconnect')
})

test('Bot Mode reopens the original chat behind an offline OpenSSH alias', async () => {
  test.setTimeout(180_000)
  await verifySshBotChat('default', 'reconnect')
})

test('Bot Mode opens the new OpenSSH alias target after a live edit', async () => {
  test.setTimeout(180_000)
  await verifySshBotChat('default', 'edit')
})

test('Bot Mode opens the replacement OpenSSH installation after an endpoint edit', async () => {
  test.setTimeout(180_000)
  await verifySshBotChat('default', 'replace')
})

test('Bot Mode refuses a changed OpenSSH host key before explicit trust update', async () => {
  test.setTimeout(180_000)
  await verifySshBotChat('default', 'rotate')
})
