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
import { type CoreSandbox, createCoreSandbox, freePort, launchCoreApp, sandboxProcesses } from './harness'
import { startScriptedProvider } from './provider'

const profile = 'scout'
const title = 'Bot Chat'
const installId = '1'.repeat(32)
const remoteId = 'spare'
const writeMethods = new Set(['session.create', 'prompt.submit'])

interface Route {
  connectionId: string
  mode: 'local' | 'remote'
  primary?: true
  profile: string
  targetProfile: string
}

interface DesktopBridge {
  getProfileRoutes(profiles: string[]): Promise<Route[]>
  getConnectionFor(dial: Pick<Route, 'connectionId' | 'profile'>): Promise<{
    baseUrl: string
    mode: string
    connectionId: string
    registryScoped: boolean
  }>
}

interface DesktopSDK {
  profileRoutes(): Promise<Route[]>
  agents(): Promise<{
    primaryConnectionId: string
    sources: { connectionId: string; kind: string; reachable: boolean; installId?: string; error?: string }[]
    agents: { connectionId: string; profile: string; targetProfile: string; handle: string }[]
  }>
  requestProfile<T>(
    route: Route | string,
    method: string,
    params: Record<string, unknown>,
    timeoutMs: number,
    options: { spawnPriority: 'foreground' }
  ): Promise<T>
}

interface Chat {
  id: string
  messages: [string, string][]
}

declare global {
  interface Window {
    __E07_INSTALL_AMBIGUITY__?: DesktopSDK
  }
}

function prepareHomes(
  local: CoreSandbox,
  remote: CoreSandbox,
  modelUrl: string,
  remotePort: number,
  fullCopy: boolean
) {
  const localEnv = privateEnv(local)
  const remoteEnv = privateEnv(remote)
  const localLabel = fullCopy ? 'donor' : 'local'
  const remoteLabel = fullCopy ? 'donor' : 'spare'
  seedInstall(local, localEnv, modelUrl, profile, localLabel, installId)

  if (fullCopy) {
    // Copy only the fixture's never-started home, before either gateway or the Desktop plugin exists.
    expect(fs.readdirSync(remote.hermesHome)).toEqual([])
    fs.rmdirSync(remote.hermesHome)
    fs.cpSync(local.hermesHome, remote.hermesHome, { recursive: true, errorOnExist: true, force: false })
    fs.chmodSync(remote.hermesHome, 0o700)
    expect(storedChats(remote.hermesHome, profile)).toEqual(storedChats(local.hermesHome, profile))

    const configPath = path.join(remote.hermesHome, 'config.yaml')
    const config = fs.readFileSync(configPath, 'utf8')
    const disabled = 'webapp:\n  enabled: false\n'
    expect(config.endsWith(disabled)).toBe(true)
    fs.writeFileSync(
      configPath,
      config.replace(disabled, `webapp:\n  enabled: true\n  host: 127.0.0.1\n  port: ${remotePort}\n`)
    )
  } else {
    seedInstall(remote, remoteEnv, modelUrl, profile, remoteLabel, '2'.repeat(32), remotePort)
    fs.copyFileSync(path.join(local.hermesHome, 'install_id'), path.join(remote.hermesHome, 'install_id'))
  }

  const installations = [
    { box: local, env: localEnv, label: localLabel, append: 'fixture-local-post-copy' },
    { box: remote, env: remoteEnv, label: remoteLabel, append: 'fixture-remote-post-copy' }
  ]

  return installations.map(({ box, env, label, append }) => {
    expect(Buffer.byteLength(path.join(box.hermesHome, 'gateway.sock'))).toBeLessThan(104)
    const id = `fixture-${label}-${profile}`
    const messages: Chat['messages'] = [['user', id]]
    if (fullCopy) {
      runPython(
        env,
        `
import sys
from hermes_constants import get_hermes_home
from hermes_state import SessionDB
profile, session_id, text = sys.argv[1:]
with SessionDB(get_hermes_home() / "profiles" / profile / "state.db") as db:
    db.append_message(session_id, "assistant", text)
`,
        profile,
        id,
        append
      )
      messages.push(['assistant', append])
    }

    return { box, env, defaultId: `fixture-${label}-default`, chat: { id, messages } }
  })
}

function nativeChat(gateway: Gateway, chat: Chat) {
  return JSON.parse(
    runPython(
      gateway.env,
      `
import asyncio
import json
import sys
from hermes_cli.gateway_client import connect_gateway
from hermes_cli.gateway_runtime import discover_gateway_endpoint
from hermes_cli.install_identity import get_install_id
from hermes_constants import get_hermes_home

async def read():
    profile, session_id = sys.argv[1:]
    home = get_hermes_home() / "profiles" / profile
    endpoint = discover_gateway_endpoint(home, timeout=1).endpoint
    assert endpoint is not None
    async with asyncio.timeout(6), connect_gateway(endpoint=endpoint) as client:
        listing = await client.rpc("session.list", title="Bot Chat", include_hidden=True, limit=11)
        transcript = await client.rpc("session.transcript", session_id=session_id, order="oldest", limit=12)
    print(json.dumps({
        "installId": get_install_id(), "origin": endpoint.api_origin,
        "ids": [[row["id"], row["resolved_id"]] for row in listing["sessions"]],
        "transcript": {
            "id": transcript["session_id"],
            "rows": [[row["row_kind"], row["role"], row["text"]] for row in transcript["rows"]],
        },
    }))

asyncio.run(read())
`,
      profile,
      chat.id
    )
  )
}

function transcriptOf(chat: Chat) {
  return { id: chat.id, rows: chat.messages.map(([role, text]) => ['message', role, text]) }
}

function requestChat(page: Page, route: Route | string, limit: number) {
  return page.evaluate(
    async ({ route, limit, title }) => {
      try {
        const result = await window.__E07_INSTALL_AMBIGUITY__!.requestProfile<{
          sessions: { id: string; resolved_id: string }[]
        }>(
          route,
          'session.list',
          { profile: typeof route === 'string' ? route : route.targetProfile, title, include_hidden: true, limit },
          12_000,
          { spawnPriority: 'foreground' }
        )

        return { ids: result.sessions.map(row => [row.id, row.resolved_id]) }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)

        return {
          refused: /requires a route descriptor from host\.profileRoutes/.test(message)
            ? 'descriptor-required'
            : 'unexpected'
        }
      }
    },
    { route, limit, title }
  )
}

function requestTranscript(page: Page, route: Route, id: string, limit: number) {
  return page.evaluate(
    async ({ route, limit, id }) => {
      const result = await window.__E07_INSTALL_AMBIGUITY__!.requestProfile<{
        session_id: string
        rows: { row_kind: string; role: string; text: string }[]
      }>(
        route,
        'session.transcript',
        { profile: route.targetProfile, session_id: id, order: 'oldest', limit },
        12_000,
        { spawnPriority: 'foreground' }
      )

      return { id: result.session_id, rows: result.rows.map(({ row_kind, role, text }) => [row_kind, role, text]) }
    },
    { route, limit, id }
  )
}

function observeDiscovery(page: Page) {
  return page.evaluate(async profile => {
    const sdk = window.__E07_INSTALL_AMBIGUITY__!
    const bridge = (window as unknown as { hermesDesktop: DesktopBridge }).hermesDesktop
    const roster = await sdk.agents()
    const named = (routes: Route[]) => routes.filter(route => route.profile === profile)

    return {
      primary: roster.primaryConnectionId,
      sources: roster.sources
        .map(({ connectionId, kind, reachable, installId, error }) => ({
          connectionId,
          kind,
          reachable,
          installId,
          error: Boolean(error)
        }))
        .sort((left, right) => left.connectionId.localeCompare(right.connectionId)),
      named: roster.agents
        .filter(row => row.profile === profile)
        .map(({ connectionId, profile, targetProfile, handle }) => ({ connectionId, profile, targetProfile, handle })),
      preload: named(await bridge.getProfileRoutes([])),
      sdk: named(await sdk.profileRoutes())
    }
  }, profile)
}

async function verifyInstallAmbiguity(fullCopy: boolean) {
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
    const remotePort = await freePort()
    const [local, remote] = prepareHomes(localBox, remoteBox, provider.url, remotePort, fullCopy)
    const plugin = path.join(localBox.hermesHome, 'desktop-plugins', 'e07-install-ambiguity')
    fs.mkdirSync(plugin, { recursive: true })
    fs.writeFileSync(
      path.join(plugin, 'plugin.js'),
      `
import { host } from '@hermes/plugin-sdk'
export default {
  id: 'e07-install-ambiguity',
  register() { globalThis.__E07_INSTALL_AMBIGUITY__ = host }
}
`
    )

    const localGateway = startGateway(localBox, local!.env)
    gateways.push(localGateway)
    const remoteGateway = startGateway(remoteBox, remote!.env)
    gateways.push(remoteGateway)
    const [localEndpoint, remoteEndpoint] = await Promise.all([
      waitForEndpoint(localGateway, profile),
      waitForEndpoint(remoteGateway, profile)
    ])
    expect(localEndpoint.pid).not.toBe(remoteEndpoint.pid)
    expect(localEndpoint.profileId).not.toBe(remoteEndpoint.profileId)
    expect(localEndpoint.instanceId).not.toBe(remoteEndpoint.instanceId)
    expect(localEndpoint.origin).not.toBe(remoteEndpoint.origin)
    expect(remoteEndpoint.origin).toBe(`http://127.0.0.1:${remotePort}`)
    const localPort = new URL(localEndpoint.origin).port
    const token = fs.readFileSync(path.join(remoteBox.hermesHome, 'webapp', 'session-token'), 'utf8').trim()
    expect(/^[A-Za-z0-9_-]{43}$/.test(token), 'native test Webapp token is available').toBe(true)
    // Confirm the actual saved source inventory supplies the row that Desktop will collapse.
    const response = await fetch(new URL('/api/profiles', remoteEndpoint.origin), {
      headers: { 'X-Hermes-Session-Token': token },
      redirect: 'error',
      signal: AbortSignal.timeout(8_000)
    })
    expect(response.status, 'authenticated remote profile inventory').toBe(200)
    const inventory = (await response.json()) as { profiles: { name: string }[] }
    expect(inventory.profiles.filter(row => row.name === profile)).toHaveLength(1)
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

    const owners = [
      { ...local!, gateway: localGateway, endpoint: localEndpoint },
      { ...remote!, gateway: remoteGateway, endpoint: remoteEndpoint }
    ]
    const readNative = () => owners.map(({ gateway, chat }) => nativeChat(gateway, chat))
    const expectedNative = owners.map(({ chat, endpoint }) => ({
      installId,
      origin: endpoint.origin,
      ids: [[chat.id, chat.id]],
      transcript: transcriptOf(chat)
    }))
    expect(readNative()).toEqual(expectedNative)
    const snapshots = () => owners.map(({ box }) => storedChats(box.hermesHome, profile))
    const before = snapshots()
    expect(before).toEqual(
      owners.map(({ defaultId, chat }) =>
        [{ id: defaultId, messages: [['user', defaultId]] }, chat].map(({ id, messages }) => ({
          sessions: [{ id, title, hidden: 1, parent_session_id: null }],
          messages: messages.map(([role, content], index) => ({ id: index + 1, session_id: id, role, content })),
          admissions: []
        }))
      )
    )

    const live = await launchCoreApp(local!.env)
    app = live.app
    const { page } = live
    const sockets = new Map<WireFrame, WireSocket>()
    const wire = observeWire(page, sockets)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForFunction(
      () => typeof window.__E07_INSTALL_AMBIGUITY__?.requestProfile === 'function',
      undefined,
      {
        timeout: 45_000
      }
    )
    const localRoute: Route = { connectionId: 'local', mode: 'local', primary: true, profile, targetProfile: profile }
    const remoteRoute: Route = { connectionId: remoteId, mode: 'remote', profile, targetProfile: profile }
    const expectedDiscovery = {
      primary: 'local',
      sources: [
        { connectionId: 'local', kind: 'local', reachable: true, installId, error: false },
        { connectionId: remoteId, kind: 'remote', reachable: true, installId, error: false }
      ],
      named: [{ connectionId: 'local', profile, targetProfile: profile, handle: profile }],
      preload: [localRoute],
      sdk: [localRoute]
    }
    await expect
      .poll(() => observeDiscovery(page), { timeout: 30_000, intervals: [250, 500, 1_000] })
      .toEqual(expectedDiscovery)

    // The saved source is still registered for explicit addressing even though its discovery row collapsed.
    const dials = await page.evaluate(
      async routes => {
        const bridge = (window as unknown as { hermesDesktop: DesktopBridge }).hermesDesktop

        return Promise.all(
          routes.map(async ({ connectionId, profile }) => {
            const dial = await bridge.getConnectionFor({ connectionId, profile })

            return { id: dial.connectionId, origin: dial.baseUrl, mode: dial.mode, scoped: dial.registryScoped }
          })
        )
      },
      [localRoute, remoteRoute]
    )
    expect(dials).toEqual([
      { id: 'local', origin: localEndpoint.origin, mode: 'local', scoped: true },
      { id: remoteId, origin: remoteEndpoint.origin, mode: 'remote', scoped: true }
    ])
    const verifyWire = (method: string, limit: number, port: string, savedToken: boolean, chat?: Chat) => {
      const frames = wire.filter(frame => frame.method === method && frame.limit === limit && (chat || lookup(frame)))
      expect(frames).toEqual([
        {
          port,
          method,
          profile,
          sessionId: chat?.id,
          title: chat ? undefined : title,
          includeHidden: chat ? undefined : true,
          limit,
          reply: {}
        }
      ])
      expect(sockets.get(frames[0]!)).toMatchObject({ savedToken })
    }
    expect(await requestChat(page, localRoute, 17)).toEqual({ ids: expectedNative[0]!.ids })
    verifyWire('session.list', 17, localPort, false)
    expect(await requestChat(page, remoteRoute, 18)).toEqual({ ids: expectedNative[1]!.ids })
    verifyWire('session.list', 18, String(remotePort), true)
    expect(await requestChat(page, profile, 19)).toEqual({ refused: 'descriptor-required' })
    expect(wire.filter(frame => lookup(frame) && frame.limit === 19)).toEqual([])

    const reads = [
      { route: localRoute, chat: local!.chat, port: localPort, savedToken: false },
      { route: remoteRoute, chat: remote!.chat, port: String(remotePort), savedToken: true },
      { route: localRoute, chat: local!.chat, port: localPort, savedToken: false }
    ]
    for (const [index, { route, chat, port, savedToken }] of reads.entries()) {
      const limit = 21 + index
      expect(await requestTranscript(page, route, chat.id, limit)).toEqual(transcriptOf(chat))
      verifyWire('session.transcript', limit, port, savedToken, chat)
    }
    expect(await observeDiscovery(page)).toEqual(expectedDiscovery)
    expect(readNative()).toEqual(expectedNative)
    expect(snapshots()).toEqual(before)
    expect(wire.filter(frame => writeMethods.has(frame.method))).toEqual([])
    expect(readEndpoint(localGateway, profile)).toEqual(localEndpoint)
    expect(readEndpoint(remoteGateway, profile)).toEqual(remoteEndpoint)
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
}

test('copied install marker collapses discovery while exact sources stay distinct', async () => {
  await verifyInstallAmbiguity(false)
})

test('stopped home copy scopes equal canonical IDs to distinct sources', async () => {
  await verifyInstallAmbiguity(true)
})
