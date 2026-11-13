/** Overlay in the pinned Hermes apps/desktop/e2e/core directory. */
import { spawnSync } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'

import { expect, type ElectronApplication, test } from '@playwright/test'

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
import {
  configureSavedWebapp,
  type Gateway,
  privateEnv,
  readEndpoint,
  runPython,
  seedInstall,
  startGateway,
  stopGateway,
  waitForEndpoint
} from './desktop_native_gateway_fixture'
import { composer, createCoreSandbox, freePort, REPO_ROOT, sandboxProcesses } from './harness'
import { startScriptedProvider } from './provider'

const fixture = 'apps.desktop.e2e.core.desktop_compressed_adoption_fixture'
const profile = 'scout'
const root = 'fixture-adopt-root'
const tip = 'fixture-adopt-tip'
const rootMarker = 'fixture-compressed-root-only'
const tipMarker = 'fixture-compressed-tip-only'
const defaultMarker = 'fixture-default-same-tip-id'

interface StoredRow {
  id: string
  title: string | null
  hidden: boolean
  parent: string | null
  owner: 'historical' | 'host' | 'other'
  chatId: string | null
  endReason: string | null
  routed: boolean
}

interface AdoptionInventory {
  bindings: {
    kind: 'legacy' | 'policy'
    id: string
    keyMatches: boolean
    owner: boolean
    profile: boolean
    targetMatches: boolean
    routeMatches: boolean
  }[]
  rows: StoredRow[]
}

interface HistoryRead {
  id: string
  scoped: boolean
  tokenHeader: boolean
  includesCompacted: boolean
  status: number
  targetMatches?: boolean
  orderedMarkers?: boolean
  rootMarkers?: number
  tipMarkers?: number
  decoyMarkers?: number
}

for (const mode of ['local private ticket', 'saved Webapp token'] as const) {
  test(`native adoption hydrates the exact compressed Bot Chat over the ${mode}`, async () => {
    await verifyCompressedHistory(mode === 'saved Webapp token')
  })
}

async function verifyCompressedHistory(savedToken: boolean) {
  test.setTimeout(180_000)
  expect(process.platform).toBe('linux')
  expect(path.isAbsolute(process.env.HERMES_E2E_PYTHON ?? '')).toBe(true)
  expect(process.env.HERMES_E2E_CORE_ROOT).toBeTruthy()
  const provider = await startScriptedProvider()
  const box = createCoreSandbox('a')
  const peer = savedToken ? createCoreSandbox('b') : null
  const gateways: Gateway[] = []
  const connectionId = savedToken ? 'spare' : 'local'
  let app: ElectronApplication | undefined
  let completed = false
  try {
    const env = privateEnv(box)
    const control = path.join(box.root, 'adoption')
    fs.mkdirSync(control, { mode: 0o700 })
    fs.writeFileSync(path.join(control, 'rest.jsonl'), '', { mode: 0o600 })
    const webappPort = savedToken ? await freePort() : undefined
    seedInstall(box, env, provider.url, profile, 'adopt', '8'.repeat(32), webappPort)
    runPython(env, `from ${fixture} import seed; seed()`)
    expect(Buffer.byteLength(path.join(box.hermesHome, 'gateway.sock'))).toBeLessThan(104)
    const desktop = peer ?? box
    installCanonicalObserver(desktop.hermesHome)
    const gateway = startGateway(box, { ...env, HERMES_ADOPTION_OBSERVER: control }, ['-m', fixture])
    gateways.push(gateway)
    const endpoint = await waitForEndpoint(gateway, profile)
    let desktopEnv = env
    let peerGateway: Gateway | undefined
    const peerControl = peer && path.join(peer.root, 'adoption')
    if (peer && peerControl) {
      desktopEnv = privateEnv(peer)
      seedInstall(peer, desktopEnv, provider.url, profile, 'peer', '9'.repeat(32))
      runPython(desktopEnv, `from ${fixture} import seed_peer; seed_peer()`)
      fs.mkdirSync(peerControl, { mode: 0o700 })
      fs.writeFileSync(path.join(peerControl, 'rest.jsonl'), '', { mode: 0o600 })
      peerGateway = startGateway(peer, { ...desktopEnv, HERMES_ADOPTION_OBSERVER: peerControl }, ['-m', fixture])
      gateways.push(peerGateway)
      const peerEndpoint = await waitForEndpoint(peerGateway, profile)
      expect(peerEndpoint.instanceId).not.toBe(endpoint.instanceId)
      expect(peerEndpoint.origin).not.toBe(endpoint.origin)
      expect(endpoint.origin).toBe(`http://127.0.0.1:${webappPort}`)
      configureSavedWebapp(peer, box, endpoint.origin, connectionId, profile)
    }
    const peerEndpointBefore = peerGateway && readEndpoint(peerGateway, profile)
    const peerHistory = peer && storedChats(peer.hermesHome, profile)
    if (peerHistory) {
      expect(peerHistory.map(item => item.sessions.map(row => row.id))).toEqual([[tip], [tip]])
      expect(peerHistory.map(item => item.messages.map(row => row.content))).toEqual([
        ['fixture-peer-default-same-tip-id'],
        ['fixture-peer-scout-same-tip-id']
      ])
    }
    const port = new URL(endpoint.origin).port
    const inspect = () =>
      JSON.parse(runPython(env, `from ${fixture} import inventory; inventory()`)) as [
        AdoptionInventory,
        AdoptionInventory
      ]
    const chats = () => storedChats(box.hermesHome, profile)
    const before = inspect()
    const historyBefore = chats()
    const unbound = { owner: 'historical', chatId: null, routed: false, hidden: true }
    const legacyTip = { ...unbound, id: tip, title: null, parent: root, endReason: 'session_switch' }
    expect(before).toEqual([
      { bindings: [], rows: [{ ...unbound, id: tip, title: 'Bot Chat', parent: null, endReason: null }] },
      {
        bindings: [],
        rows: [{ ...unbound, id: root, title: 'Bot Chat', parent: null, endReason: 'compression' }, legacyTip]
      }
    ])
    expect(historyBefore.map(item => item.admissions)).toEqual([[], []])
    expect(
      historyBefore.map(item => item.messages.map(({ session_id, role, content }) => [session_id, role, content]))
    ).toEqual([
      [[tip, 'user', defaultMarker]],
      [
        [root, 'user', rootMarker],
        [tip, 'assistant', tipMarker]
      ]
    ])
    const adopt = (...flags: string[]) => {
      const result = spawnSync(
        process.env.HERMES_E2E_PYTHON!,
        ['-m', 'hermes_cli.main', '-p', profile, 'sessions', 'adopt', ...flags],
        {
          cwd: REPO_ROOT,
          env,
          encoding: 'utf8',
          timeout: 30_000
        }
      )
      expect(result.status, 'real CLI adopt completed').toBe(0)
      return {
        eligible: result.stdout.includes('1 pre-gateway chat(s) to adopt'),
        dry: result.stdout.includes('Dry run: nothing was adopted.'),
        adopted: result.stdout.includes('Adopted 1 chat(s).'),
        empty: result.stdout.includes('Nothing to adopt')
      }
    }
    expect(adopt('--dry-run')).toEqual({ eligible: true, dry: true, adopted: false, empty: false })
    expect(inspect()).toEqual(before)
    expect(chats()).toEqual(historyBefore)
    expect(adopt()).toEqual({ eligible: true, dry: false, adopted: true, empty: false })
    const after = inspect()
    expect(after[0]).toEqual(before[0])
    expect(after[1]).toEqual({
      bindings: ['legacy', 'policy'].map(kind => ({
        kind,
        id: tip,
        keyMatches: true,
        owner: true,
        profile: true,
        targetMatches: true,
        routeMatches: true
      })),
      rows: [before[1].rows[0], { ...legacyTip, owner: 'host', chatId: tip, routed: true }]
    })
    expect(chats()).toEqual(historyBefore)
    expect(adopt()).toEqual({ eligible: false, dry: false, adopted: false, empty: true })
    expect(inspect()).toEqual(after)
    expect(readEndpoint(gateway, profile)).toEqual(endpoint)
    runPython(env, `import asyncio; from ${fixture} import assert_canonical_lineage; asyncio.run(assert_canonical_lineage())`)

    const live = await launchBotDesktop(desktopEnv)
    app = live.app
    const { page } = live
    const sockets = new Map<WireFrame, WireSocket>()
    const wire = observeWire(page, sockets)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(composer(page)).toBeVisible({ timeout: 45_000 })
    await page.waitForFunction(() => Boolean(window.__E07_CANONICAL_FOCUS__), undefined, { timeout: 45_000 })
    if (savedToken) {
      await expect
        .poll(() => page.evaluate(() => window.__E07_CANONICAL_ROUTE__?.()), { timeout: 45_000 })
        .toEqual({ connectionId, profile, gateway: 'open' })
    }
    await page
      .getByRole('button', { name: 'Bots', exact: true })
      .or(page.getByRole('tab', { name: 'Bots', exact: true }))
      .first()
      .click()
    const roster = page.locator('[data-slot="bots-roster"]')
    const scout = roster.locator(`[data-roster-key="${connectionId}::${profile}"]`)
    if (savedToken) {
      await expect(roster.locator('[data-roster-key="local::scout"]')).toBeVisible()
    }
    await expect(scout).toBeVisible()
    const oldFocus = await focus(page)
    expect(oldFocus.id).not.toBe(tip)
    const from = wire.length
    for (const directory of peerControl ? [control, peerControl] : [control]) {
      fs.writeFileSync(path.join(directory, 'armed'), '', { flag: 'wx', mode: 0o600 })
    }
    await scout.click()
    const viewport = page.locator('[data-slot="aui_thread-viewport"]').filter({ visible: true }).first()
    for (const marker of [rootMarker, tipMarker]) {
      const message = viewport.getByText(marker, { exact: true })
      await expect(message).toBeVisible({ timeout: 35_000 })
      await expect(message).toHaveCount(1)
    }
    for (const marker of [defaultMarker, 'fixture-peer-default-same-tip-id', 'fixture-peer-scout-same-tip-id']) {
      await expect(viewport.getByText(marker, { exact: true })).toHaveCount(0)
    }
    await expect.poll(() => focus(page)).toEqual({ id: tip, owner: { connectionId, profile } })
    await expect(page.getByRole('alert').filter({ hasText: /Could not open .*’s chat/ })).toHaveCount(0)
    const clickFrames = wire.slice(from)
    const reads = clickFrames.filter(lookup)
    expect(reads).toEqual([
      {
        port,
        method: 'session.list',
        profile,
        sessionId: undefined,
        title: 'Bot Chat',
        includeHidden: true,
        limit: 200,
        reply: {}
      }
    ])
    const opens = clickFrames.filter(frame => ['session.resume', 'session.activate'].includes(frame.method))
    expect(opens.some(frame => frame.method === 'session.resume')).toBe(true)
    for (const frame of opens) {
      expect(frame).toMatchObject({ port, profile, sessionId: tip, reply: {} })
      expect(sockets.get(frame)).toMatchObject({ savedToken })
    }
    const historyReads = fs
      .readFileSync(path.join(control, 'rest.jsonl'), 'utf8')
      .split('\n')
      .filter(Boolean)
      .map(line => JSON.parse(line) as HistoryRead)
    expect(historyReads).toContainEqual({
      id: tip,
      scoped: true,
      tokenHeader: savedToken,
      includesCompacted: true,
      status: 200,
      targetMatches: true,
      orderedMarkers: true,
      rootMarkers: 1,
      tipMarkers: 1,
      decoyMarkers: 0
    })
    expect(historyReads.every(entry => entry.id === tip && entry.scoped && entry.tokenHeader === savedToken)).toBe(true)
    if (peerControl) {
      expect(fs.readFileSync(path.join(peerControl, 'rest.jsonl'), 'utf8')).toBe('')
    }
    expect(wire.filter(frame => ['session.create', 'prompt.submit'].includes(frame.method))).toEqual([])
    expect(chats()).toEqual(historyBefore)
    expect(inspect()).toEqual(after)
    expect(readEndpoint(gateway, profile)).toEqual(endpoint)
    if (peer && peerGateway) {
      expect(storedChats(peer.hermesHome, profile)).toEqual(peerHistory)
      expect(readEndpoint(peerGateway, profile)).toEqual(peerEndpointBefore)
    }
    expect(provider.completions.length).toBe(0)
    completed = true
  } finally {
    await app?.close().catch(() => undefined)
    const stopped = await Promise.allSettled(gateways.map(stopGateway))
    await provider.close()
    for (const sandbox of peer ? [box, peer] : [box]) {
      const live = sandboxProcesses(sandbox)
      sandbox.cleanup()
      if (completed) expect(live).toHaveLength(0)
    }
    if (completed) expect(stopped.every(result => result.status === 'fulfilled')).toBe(true)
  }
}
