/** Overlay in the pinned Hermes apps/desktop/e2e/core directory. */
import { spawnSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import * as fs from 'node:fs'
import * as path from 'node:path'

import { chromium, expect, type Browser, type ElectronApplication, type Page, test } from '@playwright/test'

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
import { composer, createCoreSandbox, freePort, launchCoreApp, REPO_ROOT, sandboxProcesses } from './harness'
import { startScriptedProvider } from './provider'

const profile = 'scout'
const username = 'fixture-owner'
const title = 'Bot Chat'

declare global {
  interface Window {
    __E07_NATIVE_CHAT_READ__?: (limit: number) => Promise<string[][]>
    __E07_NATIVE_GATEWAY_OPEN__?: () => boolean
  }
}

function configureBasicSignIn(
  gateway: ReturnType<typeof createCoreSandbox>,
  env: Record<string, string>,
  label: string
) {
  const basic = path.join(env.HERMES_BUNDLED_PLUGINS!, 'dashboard_auth', 'basic')
  fs.mkdirSync(basic, { recursive: true, mode: 0o700 })
  for (const file of ['plugin.yaml', '__init__.py']) {
    fs.copyFileSync(path.join(REPO_ROOT, 'plugins', 'dashboard_auth', 'basic', file), path.join(basic, file))
  }

  const password = randomBytes(24).toString('hex')
  const hash = spawnSync(
    process.env.HERMES_E2E_PYTHON!,
    [
      '-c',
      'import sys; from plugins.dashboard_auth.basic import hash_password; print(hash_password(sys.stdin.read()))'
    ],
    { cwd: REPO_ROOT, env, input: password, encoding: 'utf8', timeout: 10_000 }
  )
  expect(hash.status, 'the bundled basic provider hashes the fixture password').toBe(0)
  const configPath = path.join(gateway.hermesHome, 'config.yaml')
  const config = fs.readFileSync(configPath, 'utf8')
  const secret = randomBytes(32).toString('hex')
  fs.writeFileSync(
    configPath,
    `${config}  public_url: http://fixture-${label}.test\ndashboard:\n  basic_auth:\n    username: ${username}\n` +
      `    password_hash: '${hash.stdout.trim()}'\n    secret: '${secret}'\n`
  )
  fs.chmodSync(configPath, 0o600)

  return password
}

function adoptChats(env: Record<string, string>, profile: string) {
  runPython(
    env,
    `
import asyncio
import sys
from hermes_cli.gateway_client import connect_gateway
from hermes_cli.gateway_runtime import discover_gateway_endpoint
from hermes_constants import get_hermes_home

async def read():
    root = get_hermes_home()
    for home in (root, root / "profiles" / sys.argv[1]):
        endpoint = discover_gateway_endpoint(home, timeout=1).endpoint
        assert endpoint is not None
        async with asyncio.timeout(4), connect_gateway(endpoint=endpoint) as client:
            listing = await client.rpc("session.list", title="Bot Chat", include_hidden=True, limit=11)
            assert len(listing["sessions"]) == 1

asyncio.run(read())
`,
    profile
  )
}

function observe(page: Page) {
  const sockets = new Map<WireFrame, WireSocket>()
  const wire = observeWire(page, sockets)

  return { sockets, wire }
}

function loginForm(page: Page) {
  return page.locator('form[data-provider="basic"]')
}

async function signIn(page: Page, origin: string, password: string) {
  await expect(page).toHaveURL(url => url.origin === origin && url.pathname === '/login')
  const form = loginForm(page)
  await expect(form).toBeVisible()
  // Keep fixture password out of Playwright action logs. The actual form still submits normally.
  await form.evaluate(
    (node, { username, password }) => {
      node.querySelector<HTMLInputElement>('input[name="username"]')!.value = username
      node.querySelector<HTMLInputElement>('input[name="password"]')!.value = password
    },
    { username, password }
  )
  await form.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(url => url.origin === origin && url.pathname !== '/login', { timeout: 30_000 })
  await expect(composer(page)).toBeVisible({ timeout: 45_000 })
}

async function showBots(page: Page) {
  await page
    .getByRole('button', { name: 'Bots', exact: true })
    .or(page.getByRole('tab', { name: 'Bots', exact: true }))
    .first()
    .click()
  await expect(page.locator('[data-slot="bots-roster"]')).toBeVisible()
}

async function openChat(
  page: Page,
  observation: ReturnType<typeof observe>,
  profile: string,
  marker: string,
  decoy: string,
  port: string
) {
  const row = page.locator(`[data-slot="bots-roster"] [data-roster-key="local::${profile}"]`)
  await expect(row).toContainText(marker)
  const from = observation.wire.length
  await row.click()
  const view = page.locator('[data-slot="aui_thread-viewport"]').filter({ visible: true }).first()
  await expect(view.getByText(marker, { exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(view.getByText(decoy, { exact: true })).toHaveCount(0)
  await expect
    .poll(() => observation.wire.slice(from).filter(lookup))
    .toEqual([
      { port, method: 'session.list', profile, sessionId: undefined, title, includeHidden: true, limit: 200, reply: {} }
    ])
  const socket = observation.sockets.get(observation.wire.slice(from).find(lookup)!)
  expect(socket).toMatchObject({ closed: false, savedToken: false })

  return socket!
}

function installNativeRead(home: string) {
  const plugin = path.join(home, 'desktop-plugins', 'e07-native-read')
  fs.mkdirSync(plugin, { recursive: true })
  fs.writeFileSync(
    path.join(plugin, 'plugin.js'),
    `
import { host } from '@hermes/plugin-sdk'
export default {
  id: 'e07-native-read',
  register() {
    globalThis.__E07_NATIVE_GATEWAY_OPEN__ = () => host.state.gateway.get() === 'open'
    globalThis.__E07_NATIVE_CHAT_READ__ = async limit => {
      const { sessions } = await host.request('session.list', {
        profile: 'default', title: 'Bot Chat', include_hidden: true, limit
      }, 12000)
      return sessions.map(row => [row.id, row.resolved_id])
    }
  }
}
`
  )
}

test('stock Webapp sign-out closes the selected browser while its native client and the other root stay connected', async () => {
  test.setTimeout(180_000)
  expect(process.platform).toBe('linux')
  const executablePath = process.env.HERMES_E2E_CHROMIUM
  expect(path.isAbsolute(executablePath ?? ''), 'the runner supplies an explicit Chromium executable').toBe(true)
  expect(path.isAbsolute(process.env.HERMES_E2E_PYTHON ?? '')).toBe(true)
  expect(process.env.HERMES_E2E_CORE_ROOT).toBeTruthy()

  const provider = await startScriptedProvider()
  const target = createCoreSandbox('a')
  const peer = createCoreSandbox('b')
  const gateways: Gateway[] = []
  let browser: Browser | undefined
  let nativeApp: ElectronApplication | undefined
  let completed = false
  try {
    const targetEnv = privateEnv(target)
    const peerEnv = privateEnv(peer)
    const targetPort = await freePort()
    const peerPort = await freePort()
    expect(targetPort).not.toBe(peerPort)
    seedInstall(target, targetEnv, provider.url, profile, 'target', 'a'.repeat(32), targetPort)
    seedInstall(peer, peerEnv, provider.url, profile, 'peer', 'b'.repeat(32), peerPort)
    const targetPassword = configureBasicSignIn(target, targetEnv, 'target')
    const peerPassword = configureBasicSignIn(peer, peerEnv, 'peer')
    installNativeRead(target.hermesHome)
    const targetGateway = startGateway(target, targetEnv)
    gateways.push(targetGateway)
    const peerGateway = startGateway(peer, peerEnv)
    gateways.push(peerGateway)
    const [targetEndpoint, peerEndpoint] = await Promise.all([
      waitForEndpoint(targetGateway, profile),
      waitForEndpoint(peerGateway, profile)
    ])
    expect(targetEndpoint.origin).toBe(`http://127.0.0.1:${targetPort}`)
    expect(peerEndpoint.origin).toBe(`http://127.0.0.1:${peerPort}`)
    expect(targetEndpoint.pid).not.toBe(peerEndpoint.pid)
    expect(targetEndpoint.instanceId).not.toBe(peerEndpoint.instanceId)
    adoptChats(targetEnv, profile)
    adoptChats(peerEnv, profile)
    const snapshots = () => [target, peer].map(box => storedChats(box.hermesHome, profile))
    const before = snapshots()
    expect(before.flat().map(store => store.sessions.map(row => row.id))).toEqual([
      ['fixture-target-default'],
      ['fixture-target-scout'],
      ['fixture-peer-default'],
      ['fixture-peer-scout']
    ])
    expect(before.flat().every(store => store.admissions.length === 0)).toBe(true)

    browser = await chromium.launch({ executablePath, env: targetEnv })
    const targetPage = await (await browser.newContext({ viewport: { width: 1280, height: 860 } })).newPage()
    const peerPage = await (await browser.newContext({ viewport: { width: 1280, height: 860 } })).newPage()
    const targetBrowser = observe(targetPage)
    const peerBrowser = observe(peerPage)
    await Promise.all([targetPage.goto(targetEndpoint.origin), peerPage.goto(peerEndpoint.origin)])
    await Promise.all([
      signIn(targetPage, targetEndpoint.origin, targetPassword),
      signIn(peerPage, peerEndpoint.origin, peerPassword)
    ])
    await Promise.all([showBots(targetPage), showBots(peerPage)])
    const targetMarker = 'fixture-target-scout'
    const peerMarker = 'fixture-peer-scout'
    const targetSocket = await openChat(
      targetPage,
      targetBrowser,
      profile,
      targetMarker,
      peerMarker,
      String(targetPort)
    )
    const peerSocket = await openChat(peerPage, peerBrowser, profile, peerMarker, targetMarker, String(peerPort))

    const native = await launchCoreApp(targetEnv)
    nativeApp = native.app
    const nativeWire = observe(native.page)
    await native.page.reload({ waitUntil: 'domcontentloaded' })
    await expect(composer(native.page)).toBeVisible({ timeout: 45_000 })
    await native.page.waitForFunction(() => window.__E07_NATIVE_GATEWAY_OPEN__?.(), undefined, { timeout: 45_000 })
    const nativeRead = async (limit: number) => {
      const ids = await native.page.evaluate(async limit => {
        try {
          return await window.__E07_NATIVE_CHAT_READ__!(limit)
        } catch {
          return null
        }
      }, limit)
      expect(ids, `native target chat read ${limit}`).toEqual([['fixture-target-default', 'fixture-target-default']])
      const frames = nativeWire.wire.filter(frame => lookup(frame) && frame.limit === limit)
      expect(frames).toEqual([
        {
          port: String(targetPort),
          method: 'session.list',
          profile: 'default',
          sessionId: undefined,
          title,
          includeHidden: true,
          limit,
          reply: {}
        }
      ])
      const socket = nativeWire.sockets.get(frames[0]!)
      expect(socket).toMatchObject({ closed: false, savedToken: false })

      return socket!
    }
    const nativeSocket = await nativeRead(31)

    const signout = spawnSync(process.env.HERMES_E2E_PYTHON!, ['-m', 'hermes_cli.main', 'webapp', '--sign-out'], {
      cwd: REPO_ROOT,
      env: targetEnv,
      encoding: 'utf8',
      timeout: 15_000
    })
    expect(signout.status, 'the selected root’s native sign-out completed').toBe(0)
    expect(/Signed out every browser: closed [1-9]\d* browser connections?\./.test(signout.stdout)).toBe(true)
    await expect.poll(() => targetSocket.closed, { timeout: 20_000 }).toBe(true)
    expect(await nativeRead(32)).toBe(nativeSocket)
    expect(
      await openChat(peerPage, peerBrowser, 'default', 'fixture-peer-default', targetMarker, String(peerPort))
    ).toBe(peerSocket)
    expect(peerSocket.closed).toBe(false)
    expect(readEndpoint(targetGateway, profile)).toEqual(targetEndpoint)
    expect(readEndpoint(peerGateway, profile)).toEqual(peerEndpoint)

    await targetPage.reload({ waitUntil: 'domcontentloaded' })
    await expect(loginForm(targetPage)).toBeVisible()
    await expect(composer(targetPage)).toBeHidden()
    await signIn(targetPage, targetEndpoint.origin, targetPassword)
    await showBots(targetPage)
    expect(await openChat(targetPage, targetBrowser, profile, targetMarker, peerMarker, String(targetPort))).not.toBe(
      targetSocket
    )
    expect(await nativeRead(33)).toBe(nativeSocket)
    expect(readEndpoint(targetGateway, profile)).toEqual(targetEndpoint)
    expect(readEndpoint(peerGateway, profile)).toEqual(peerEndpoint)
    for (const { wire } of [targetBrowser, peerBrowser, nativeWire]) {
      expect(wire.filter(frame => frame.method === 'session.create' || frame.method === 'prompt.submit')).toEqual([])
    }
    expect(snapshots()).toEqual(before)
    expect(provider.completions.length).toBe(0)
    completed = true
  } finally {
    await nativeApp?.close().catch(() => undefined)
    await browser?.close().catch(() => undefined)
    const stopped = await Promise.allSettled(gateways.map(stopGateway))
    await provider.close()
    const live = [target, peer].flatMap(sandboxProcesses)
    target.cleanup()
    peer.cleanup()
    if (completed) {
      expect(
        stopped.every(result => result.status === 'fulfilled'),
        'both owned Gateways stopped'
      ).toBe(true)
      expect(live).toHaveLength(0)
    }
  }
})
