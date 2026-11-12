/** Overlay in the pinned Hermes apps/desktop/e2e/core directory. */
import * as fs from 'node:fs'
import * as path from 'node:path'

import { expect, type ElectronApplication, type Page, test } from '@playwright/test'

import { lookup, observeWire, storedChats, type WireFrame, type WireSocket } from './desktop_bot_canonical_observer'
import {
  type Gateway,
  privateEnv,
  readEndpoint,
  runPython,
  seedInstall,
  startGateway,
  stopGateway,
  waitForEndpoint
} from './desktop_native_gateway_fixture'
import { composer, createCoreSandbox, freePort, launchCoreApp, sandboxProcesses } from './harness'
import { startScriptedProvider } from './provider'

const fixtureModule = 'apps.desktop.e2e.core.desktop_profile_retirement_fixture'
const source = 'spare'
const profile = 'scout'
const title = 'Bot Chat'
const namedChat = 'fixture-retirement-scout'
const defaultChat = 'fixture-retirement-default'
const decoyChat = 'fixture-decoy-scout'
const openMethods = new Set(['session.resume', 'session.activate'])
const writeMethods = new Set(['session.create', 'prompt.submit'])

interface Route {
  connectionId: string
  mode: 'local' | 'remote'
  profile: string
  targetProfile: string
}

interface Focus {
  id: string | null
  owner: { connectionId: string; profile: string } | null
}

interface RetirementSDK {
  profileRoutes(): Promise<Route[]>
  requestProfile<T>(route: Route, method: string, params: object, timeout: number): Promise<T>
  active(): { connectionId: string | null; profile: string; gateway: string }
  focus(): Focus
}

interface ServingState {
  pid: number
  instanceId: string
  advertised: string[]
  recorded: string[]
  locks: { default: boolean; scout: boolean }
  epochs: { default: [number, string]; scout: [number, string] }
  parked: boolean
}

declare global {
  interface Window {
    __E07_RETIREMENT_HOST__?: RetirementSDK
  }
}

function installObserver(home: string) {
  const plugin = path.join(home, 'desktop-plugins', 'e07-retirement-observer')
  fs.mkdirSync(plugin, { recursive: true })
  fs.writeFileSync(
    path.join(plugin, 'plugin.js'),
    `
import { host } from '@hermes/plugin-sdk'
export default {
  id: 'e07-retirement-observer',
  register() {
    globalThis.__E07_RETIREMENT_HOST__ = {
      profileRoutes: host.profileRoutes,
      requestProfile: host.requestProfile,
      active: () => ({
        connectionId: host.state.connectionId.get(),
        profile: host.state.profile.get(),
        gateway: host.state.gateway.get()
      }),
      focus: () => ({
        id: host.state.focusedStoredSessionId.get(),
        owner: host.state.focusedSessionOwner.get()
      })
    }
  }
}
`
  )
}

function requestChat(page: Page, route: Route, limit: number) {
  return page.evaluate(
    async ({ route, limit, title }) => {
      const sdk = window.__E07_RETIREMENT_HOST__!
      try {
        const result = await sdk.requestProfile<{ sessions: { id: string; resolved_id: string }[] }>(
          route,
          'session.list',
          { profile: route.targetProfile, title, include_hidden: true, limit },
          12_000
        )

        return { ids: result.sessions.map(row => [row.id, row.resolved_id]) }
      } catch (error) {
        const rpc = error as { code?: number; data?: { reason?: string } }

        return {
          refused: rpc?.code === 4001 && rpc.data?.reason === 'profile_mismatch' ? 'profile_mismatch' : 'unexpected'
        }
      }
    },
    { route, limit, title }
  )
}

function namedRoster(page: Page, route: Route) {
  return page.evaluate(
    async ({ route, profile }) => {
      const sdk = window.__E07_RETIREMENT_HOST__!
      const roster = await sdk.requestProfile<{
        profiles: { name: string; canonical_session?: { id: string; resolved_id: string } }[]
      }>(route, 'profiles.list', {}, 12_000)
      const row = roster.profiles.find(entry => entry.name === profile)
      if (!row) {
        return null
      }

      return {
        sessionFields: ['canonical_session', 'last_session', 'worker_session'].filter(field =>
          Object.hasOwn(row, field)
        ),
        canonical: row.canonical_session ? [row.canonical_session.id, row.canonical_session.resolved_id] : null
      }
    },
    { route, profile }
  )
}

test('saved Webapp Desktop refuses a parked named profile and reopens its chat after hot serve', async () => {
  test.setTimeout(180_000)
  expect(process.platform).toBe('linux')
  expect(path.isAbsolute(process.env.HERMES_E2E_PYTHON ?? '')).toBe(true)
  expect(process.env.HERMES_E2E_CORE_ROOT).toBeTruthy()

  const provider = await startScriptedProvider()
  const localBox = createCoreSandbox('a')
  const remoteBox = createCoreSandbox('b')
  const gateways: Gateway[] = []
  let app: ElectronApplication | undefined
  let completed = false
  try {
    const localEnv = privateEnv(localBox)
    const remoteEnv = privateEnv(remoteBox)
    const webappPort = await freePort()
    seedInstall(localBox, localEnv, provider.url, profile, 'decoy', '6'.repeat(32))
    seedInstall(remoteBox, remoteEnv, provider.url, profile, 'retirement', '7'.repeat(32), webappPort)
    for (const box of [localBox, remoteBox]) {
      expect(Buffer.byteLength(path.join(box.hermesHome, 'gateway.sock'))).toBeLessThan(104)
    }
    installObserver(localBox.hermesHome)
    const local = startGateway(localBox, localEnv)
    gateways.push(local)
    const remote = startGateway(remoteBox, remoteEnv)
    gateways.push(remote)
    const [localEndpoint, remoteEndpoint] = await Promise.all([
      waitForEndpoint(local, profile),
      waitForEndpoint(remote, profile)
    ])
    expect(localEndpoint.instanceId).not.toBe(remoteEndpoint.instanceId)
    expect(remoteEndpoint.origin).toBe(`http://127.0.0.1:${webappPort}`)
    expect(localEndpoint.origin).not.toBe(remoteEndpoint.origin)
    const localPort = new URL(localEndpoint.origin).port
    const remotePort = String(webappPort)
    const nativeState = () =>
      JSON.parse(
        runPython(remoteEnv, `import json; from ${fixtureModule} import inspect; print(json.dumps(inspect()))`)
      ) as ServingState | null
    const changeServing = (serve: boolean) =>
      runPython(remoteEnv, `from ${fixtureModule} import change_serving; change_serving(${serve ? 'True' : 'False'})`)

    const token = fs.readFileSync(path.join(remoteBox.hermesHome, 'webapp', 'session-token'), 'utf8').trim()
    expect(/^[A-Za-z0-9_-]{43}$/.test(token), 'native test Webapp token is available').toBe(true)
    const registry = path.join(localBox.userDataDir, 'connections.json')
    fs.writeFileSync(
      registry,
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
            url: remoteEndpoint.origin,
            authMode: 'token',
            token: { encoding: 'plain', value: token }
          }
        ]
      }),
      { mode: 0o600 }
    )
    fs.writeFileSync(path.join(localBox.userDataDir, 'active-profile.json'), JSON.stringify({ profile: 'default' }), {
      mode: 0o600
    })

    const live = await launchCoreApp(localEnv)
    app = live.app
    const { page } = live
    const sockets = new Map<WireFrame, WireSocket>()
    const wire = observeWire(page, sockets)
    // The first renderer may open its primary socket before Playwright sees the window.
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(composer(page)).toBeVisible({ timeout: 45_000 })
    await expect
      .poll(() => page.evaluate(() => window.__E07_RETIREMENT_HOST__?.active()), { timeout: 45_000 })
      .toEqual({ connectionId: source, profile: 'default', gateway: 'open' })
    const routes = () => page.evaluate(() => window.__E07_RETIREMENT_HOST__!.profileRoutes())
    const expectedRoutes: Route[] = [
      { connectionId: source, mode: 'remote', profile, targetProfile: profile },
      { connectionId: source, mode: 'remote', profile: 'default', targetProfile: 'default' },
      { connectionId: 'local', mode: 'local', profile, targetProfile: profile }
    ]
    let matchedRoutes: Route[][] = []
    await expect
      .poll(
        async () => {
          const available = await routes()
          matchedRoutes = expectedRoutes.map(({ connectionId, profile }) =>
            available.filter(route => route.connectionId === connectionId && route.profile === profile)
          )

          return matchedRoutes
        },
        { timeout: 30_000, intervals: [250, 500, 1_000] }
      )
      .toMatchObject(expectedRoutes.map(route => [route]))
    const [[target], [healthy], [decoy]] = matchedRoutes
    const canary = (limit: number, port: string, target: Route, reason?: string, from = 0) => {
      const sent = wire.slice(from).filter(frame => lookup(frame) && frame.limit === limit)
      expect(sent).toEqual([
        {
          port,
          method: 'session.list',
          profile: target.targetProfile,
          sessionId: undefined,
          title,
          includeHidden: true,
          limit,
          reply: reason ? { code: 4001, reason } : {}
        }
      ])
      const socket = sockets.get(sent[0]!)
      expect(socket).toBeDefined()

      return socket!
    }
    const verifyChat = async (route: Route, limit: number, port: string, id: string) => {
      expect(await requestChat(page, route, limit)).toEqual({ ids: [[id, id]] })

      return canary(limit, port, route)
    }
    const retained = await verifyChat(target, 51, remotePort, namedChat)
    expect(retained).toEqual({ closed: false, savedToken: true })
    expect(await verifyChat(healthy, 52, remotePort, defaultChat)).toBe(retained)
    expect(await verifyChat(decoy, 53, localPort, decoyChat)).not.toBe(retained)
    const positiveRoster = {
      sessionFields: ['canonical_session', 'last_session', 'worker_session'],
      canonical: [namedChat, namedChat]
    }
    expect(await namedRoster(page, healthy)).toEqual(positiveRoster)

    await page
      .getByRole('button', { name: 'Bots', exact: true })
      .or(page.getByRole('tab', { name: 'Bots', exact: true }))
      .first()
      .click()
    const roster = page.locator('[data-slot="bots-roster"]')
    const namedRow = roster.locator(`[data-roster-key="${source}::${profile}"]`)
    await expect(namedRow).toContainText(namedChat)
    await expect(roster.locator('[data-roster-key="local::scout"]')).toBeVisible()
    const viewport = page.locator('[data-slot="aui_thread-viewport"]').filter({ visible: true }).first()
    const marker = (id: string) => viewport.getByText(id, { exact: true })
    const focus = () => page.evaluate(() => window.__E07_RETIREMENT_HOST__!.focus())
    const defaultFocus = { id: defaultChat, owner: { connectionId: source, profile: 'default' } }
    await roster.locator(`[data-roster-key="${source}::default"]`).click()
    await expect(marker(defaultChat)).toBeVisible({ timeout: 45_000 })
    await expect.poll(focus).toEqual(defaultFocus)
    await expect(marker(namedChat)).toHaveCount(0)
    const snapshots = () => [localBox, remoteBox].map(box => storedChats(box.hermesHome, profile))
    const before = snapshots()
    expect(before.map(install => install.map(store => store.sessions.map(row => row.id)))).toEqual([
      [['fixture-decoy-default'], [decoyChat]],
      [[defaultChat], [namedChat]]
    ])
    expect(before.flat().every(store => store.admissions.length === 0)).toBe(true)
    const running = nativeState()!
    expect(running).toMatchObject({
      pid: remoteEndpoint.pid,
      instanceId: remoteEndpoint.instanceId,
      advertised: ['default', profile],
      recorded: ['default', profile],
      locks: { default: true, scout: true },
      parked: false
    })
    expect(running.epochs.default[1]).toBe(running.instanceId)
    expect(running.epochs.scout[1]).toBe(running.instanceId)

    changeServing(false)
    await expect.poll(nativeState, { timeout: 20_000 }).toEqual({
      ...running,
      advertised: ['default'],
      recorded: ['default'],
      locks: { default: true, scout: false },
      parked: true
    })
    expect((await routes()).find(entry => entry.connectionId === source && entry.profile === profile)).toEqual(target)
    expect(await namedRoster(page, healthy)).toEqual({ sessionFields: [], canonical: null })
    expect(await requestChat(page, target, 54)).toEqual({ refused: 'profile_mismatch' })
    expect(canary(54, remotePort, target, 'profile_mismatch')).toBe(retained)
    expect(await verifyChat(healthy, 55, remotePort, defaultChat)).toBe(retained)
    await verifyChat(decoy, 56, localPort, decoyChat)
    expect(retained.closed).toBe(false)

    const toast = page.getByRole('alert').filter({ hasText: /Could not open .*’s chat/ })
    await expect(toast).toHaveCount(0)
    await expect(namedRow).toBeVisible()
    const parkedFrom = wire.length
    await namedRow.click()
    await expect(toast).toBeVisible()
    await expect(toast).toContainText('Try again.')
    await expect(namedRow).not.toHaveAttribute('aria-busy', 'true')
    await toast.getByRole('button', { name: 'Dismiss notification', exact: true }).click()
    await expect(toast).toHaveCount(0)
    expect(await focus()).toEqual(defaultFocus)
    await expect(marker(defaultChat)).toBeVisible()
    await expect(marker(namedChat)).toHaveCount(0)
    await expect(marker(decoyChat)).toHaveCount(0)
    expect(canary(200, remotePort, target, 'profile_mismatch', parkedFrom)).toBe(retained)
    expect(
      wire.slice(parkedFrom).filter(frame => openMethods.has(frame.method) || writeMethods.has(frame.method))
    ).toEqual([])
    expect(snapshots()).toEqual(before)

    changeServing(true)
    await expect.poll(nativeState, { timeout: 20_000 }).toEqual({
      ...running,
      epochs: { ...running.epochs, scout: [running.epochs.scout[0] + 1, running.instanceId] }
    })
    expect(await verifyChat(target, 57, remotePort, namedChat)).toBe(retained)
    expect(await verifyChat(healthy, 58, remotePort, defaultChat)).toBe(retained)
    await verifyChat(decoy, 59, localPort, decoyChat)
    expect(await namedRoster(page, healthy)).toEqual(positiveRoster)
    const restoredFrom = wire.length
    await namedRow.click()
    await expect(marker(namedChat)).toBeVisible({ timeout: 45_000 })
    await expect.poll(focus).toEqual({ id: namedChat, owner: { connectionId: source, profile } })
    await expect(marker(decoyChat)).toHaveCount(0)
    await expect(toast).toHaveCount(0)
    const restored = wire.slice(restoredFrom)
    const lookupAfter = restored.filter(lookup)
    expect(lookupAfter).toEqual([
      {
        port: remotePort,
        method: 'session.list',
        profile,
        sessionId: undefined,
        title,
        includeHidden: true,
        limit: 200,
        reply: {}
      }
    ])
    expect(sockets.get(lookupAfter[0]!)).toBe(retained)
    const opened = restored.filter(frame => openMethods.has(frame.method))
    expect(opened.length).toBeGreaterThan(0)
    expect(
      opened.every(
        frame =>
          frame.port === remotePort &&
          frame.profile === profile &&
          frame.sessionId === namedChat &&
          sockets.get(frame) === retained
      )
    ).toBe(true)
    expect(wire.filter(frame => writeMethods.has(frame.method))).toEqual([])
    expect(retained.closed).toBe(false)
    expect(snapshots()).toEqual(before)
    expect(readEndpoint(remote, profile)).toEqual(remoteEndpoint)
    expect(readEndpoint(local, profile)).toEqual(localEndpoint)
    expect(provider.completions.length).toBe(0)
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
