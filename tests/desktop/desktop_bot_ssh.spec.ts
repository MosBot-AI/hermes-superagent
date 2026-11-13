/** Overlay in the pinned Hermes apps/desktop/e2e/core directory. */
import { spawn, spawnSync } from 'node:child_process'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'

import { expect, type ElectronApplication, type Page, test } from '@playwright/test'

import { launchBotDesktop } from './desktop_bot_appimage'
import { focus, installCanonicalObserver, lookup, observeWire, storedChats } from './desktop_bot_canonical_observer'
import { privateEnv, seedInstall, startGateway, stopGateway, waitForEndpoint } from './desktop_native_gateway_fixture'
import { appLogTail, composer, createCoreSandbox, freePort, REPO_ROOT, sandboxProcesses } from './harness'
import { startScriptedProvider } from './provider'

const profile = 'scout'
const connectionId = 'fixture-ssh'
const canonical = 'fixture-ssh-scout'
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

async function readAliasedChat(page: Page, routeProfile: string) {
  await page.waitForFunction(() => typeof window.__E07_SSH_ROUTE_PROBE__?.profileRoutes === 'function')
  const route = await page.evaluate(
    async ({ connectionId, routeProfile }) => {
      const routes = await window.__E07_SSH_ROUTE_PROBE__!.profileRoutes()
      return routes.find(route => route.connectionId === connectionId && route.profile === routeProfile)
    },
    { connectionId, routeProfile }
  )
  expect(route).toEqual({ connectionId, mode: 'remote', profile: routeProfile, targetProfile: profile })
  const ids = await page.evaluate(async route => {
    const result = await window.__E07_SSH_ROUTE_PROBE__!.requestProfile(
      route,
      'session.list',
      { title: 'Bot Chat', profile: route.targetProfile, include_hidden: true, limit: 17 },
      25_000,
      { spawnPriority: 'foreground' }
    )
    return result.sessions.map(({ id, resolved_id }) => [id, resolved_id])
  }, route!)
  expect(ids).toEqual([[canonical, canonical]])
}

async function verifySshBotChat(routeProfile: string) {
  const aliased = routeProfile !== profile
  expect(process.platform).toBe('linux')
  const state = process.env.HERMES_E2E_SSH_STATE
  const python = process.env.HERMES_E2E_PYTHON
  expect(path.isAbsolute(state ?? '') && path.isAbsolute(python ?? '')).toBe(true)
  const provider = await startScriptedProvider()
  const local = createCoreSandbox('a')
  const remote = createCoreSandbox('b')
  let gateway: ReturnType<typeof startGateway> | undefined
  let server: ReturnType<typeof spawn> | undefined
  let app: ElectronApplication | undefined
  let completed = false
  try {
    const localEnv = privateEnv(local)
    const remoteEnv = privateEnv(remote)
    seedInstall(local, localEnv, provider.url, profile, 'local', '1'.repeat(32))
    seedInstall(remote, remoteEnv, provider.url, profile, 'ssh', '2'.repeat(32))
    const initial = () => [local, remote].map((box) => storedChats(box.hermesHome, profile))
    const port = await freePort()
    const sshUser = os.userInfo().username
    const sshConfig = path.join(state!, 'account', '.ssh')
    const hostKey = path.join(state!, 'host')
    const clientKey = path.join(state!, 'key')
    for (const key of [hostKey, clientKey]) {
      expect(
        spawnSync('ssh-keygen', ['-q', '-t', 'ed25519', '-N', '', '-f', key], {
          env: localEnv,
          stdio: 'ignore'
        }).status
      ).toBe(0)
    }
    fs.writeFileSync(path.join(sshConfig, 'authorized_keys'), fs.readFileSync(clientKey + '.pub'), { mode: 0o600 })
    const knownHost = `[127.0.0.1]:${port} ${fs.readFileSync(hostKey + '.pub', 'utf8')}`
    fs.writeFileSync(path.join(sshConfig, 'known_hosts'), knownHost, { mode: 0o600 })
    fs.writeFileSync(
      path.join(sshConfig, 'config'),
      `Host 127.0.0.1\n  UserKnownHostsFile ${path.join(sshConfig, 'known_hosts')}\n  IdentitiesOnly yes\n`,
      { mode: 0o600 }
    )
    const remoteLauncher = path.join(remote.bin, 'hermes')
    fs.writeFileSync(
      remoteLauncher,
      `#!/bin/sh\ncd ${shellQuote(REPO_ROOT)}\nexec ${shellQuote(python!)} -m hermes_cli.main "$@"\n`,
      { mode: 0o700 }
    )
    const remoteCommand = path.join(state!, 'remote-command')
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
    const config = path.join(state!, 'sshd.conf')
    const log = path.join(state!, 'sshd.log')
    fs.writeFileSync(
      config,
      [
        'ListenAddress 127.0.0.1',
        `Port ${port}`,
        `HostKey ${hostKey}`,
        'AuthorizedKeysFile .ssh/authorized_keys',
        'UsePAM no',
        'PasswordAuthentication no',
        'KbdInteractiveAuthentication no',
        'StrictModes yes',
        `PidFile ${state!}/sshd.pid`,
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
    server = spawn('/usr/sbin/sshd', ['-D', '-E', log, '-f', config], {
      env: localEnv,
      stdio: 'ignore'
    })
    await expect.poll(() => fs.existsSync(log) && fs.readFileSync(log, 'utf8').includes('Server listening')).toBe(true)
    const preflight = spawnSync(
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
    if (preflight.status !== 0) {
      fs.writeFileSync(path.join(state!, 'preflight.log'), preflight.stderr ?? '', { mode: 0o600 })
    }
    expect(preflight.status, 'ephemeral OpenSSH key and host key accepted').toBe(0)
    expect(preflight.stdout).toBe(remote.hermesHome)
    const acceptedKeys = () => fs.readFileSync(log, 'utf8').match(/Accepted publickey/g)?.length ?? 0
    const preflightLogins = acceptedKeys()
    expect(preflightLogins).toBe(1)

    installCanonicalObserver(local.hermesHome)
    if (aliased) installRouteProbe(local.hermesHome)
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
            user: sshUser,
            port,
            keyPath: clientKey,
            remoteHermesPath: remoteLauncher,
            ...(aliased ? { remoteProfile: profile } : {})
          }
        ]
      }),
      { mode: 0o600 }
    )
    const live = await launchBotDesktop(localEnv)
    app = live.app
    const { page } = live
    const wire = observeWire(page)
    await expect(composer(page)).toBeVisible({ timeout: 45_000 })
    let aliasedPort: string | undefined
    if (aliased) {
      const from = wire.length
      await readAliasedChat(page, routeProfile)
      const reads = wire.slice(from).filter(frame => lookup(frame) && frame.limit === 17)
      expect(reads).toHaveLength(1)
      expect(reads[0]).toMatchObject({ profile, includeHidden: true, reply: {} })
      aliasedPort = reads[0]!.port
      expect(aliasedPort).not.toBe(new URL(localEndpoint.origin).port)
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
    const from = wire.length
    await row.click()
    const viewport = page.locator('[data-slot="aui_thread-viewport"]').filter({ visible: true }).first()
    await expect(viewport.getByText(canonical, { exact: true })).toBeVisible({ timeout: 55_000 })
    await expect.poll(() => focus(page)).toEqual({ id: canonical, owner: { connectionId, profile: routeProfile } })
    for (const decoy of decoys) await expect(viewport.getByText(decoy, { exact: true })).toHaveCount(0)
    const frames = wire.slice(from)
    const reads = frames.filter(lookup)
    expect(reads).toHaveLength(1)
    expect(reads[0]).toMatchObject({ method: 'session.list', profile, includeHidden: true, reply: {} })
    expect(reads[0]!.port).not.toBe(new URL(localEndpoint.origin).port)
    if (aliasedPort) expect(reads[0]!.port).toBe(aliasedPort)
    const opens = frames.filter((frame) => ['session.resume', 'session.activate'].includes(frame.method))
    expect(opens.some((frame) => frame.method === 'session.resume')).toBe(true)
    for (const frame of opens) {
      expect(frame).toMatchObject({ port: reads[0]!.port, profile, sessionId: canonical })
    }
    expect(frames.filter((frame) => ['session.create', 'prompt.submit'].includes(frame.method))).toEqual([])
    expect(initial()).toEqual(before)
    expect(provider.completions.length).toBe(0)
    expect(acceptedKeys()).toBeGreaterThan(preflightLogins)
    completed = true
  } catch (error) {
    if (app) fs.writeFileSync(path.join(state!, 'desktop.log'), appLogTail(app), { mode: 0o600 })
    throw error
  } finally {
    await app?.close().catch(() => undefined)
    try {
      if (gateway) await stopGateway(gateway)
    } finally {
      server?.kill()
      await provider.close()
      try {
        if (completed) {
          // The SSH watchdog's last bounded sleep can briefly outlive its shell.
          await expect.poll(() => [local, remote].flatMap(sandboxProcesses), { timeout: 20_000 }).toEqual([])
        }
      } finally {
        local.cleanup()
        remote.cleanup()
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
