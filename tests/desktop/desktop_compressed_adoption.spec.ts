/** Overlay in the pinned Hermes apps/desktop/e2e/core directory. */
import { spawnSync } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'

import { expect, type ElectronApplication, test } from '@playwright/test'

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
  type Gateway,
  privateEnv,
  readEndpoint,
  runPython,
  seedInstall,
  startGateway,
  stopGateway,
  waitForEndpoint
} from './desktop_native_gateway_fixture'
import { composer, createCoreSandbox, launchCoreApp, REPO_ROOT, sandboxProcesses } from './harness'
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
  includesCompacted: boolean
  status: number
  targetMatches?: boolean
  orderedMarkers?: boolean
  rootMarkers?: number
  tipMarkers?: number
  decoyMarkers?: number
}

test('native adoption of compressed chat hydrates the exact Bot Mode profile', async () => {
  test.setTimeout(180_000)
  expect(process.platform).toBe('linux')
  expect(path.isAbsolute(process.env.HERMES_E2E_PYTHON ?? '')).toBe(true)
  expect(process.env.HERMES_E2E_CORE_ROOT).toBeTruthy()
  const provider = await startScriptedProvider()
  const box = createCoreSandbox('a')
  let gateway: Gateway | undefined
  let app: ElectronApplication | undefined
  let completed = false
  try {
    const env = privateEnv(box)
    const control = path.join(box.root, 'adoption')
    fs.mkdirSync(control, { mode: 0o700 })
    fs.writeFileSync(path.join(control, 'rest.jsonl'), '', { mode: 0o600 })
    seedInstall(box, env, provider.url, profile, 'adopt', '8'.repeat(32))
    runPython(env, `from ${fixture} import seed; seed()`)
    expect(Buffer.byteLength(path.join(box.hermesHome, 'gateway.sock'))).toBeLessThan(104)
    installCanonicalObserver(box.hermesHome)
    gateway = startGateway(box, { ...env, HERMES_ADOPTION_OBSERVER: control }, ['-m', fixture])
    const endpoint = await waitForEndpoint(gateway, profile)
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

    const live = await launchCoreApp(env)
    app = live.app
    const { page } = live
    const sockets = new Map<WireFrame, WireSocket>()
    const wire = observeWire(page, sockets)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(composer(page)).toBeVisible({ timeout: 45_000 })
    await page.waitForFunction(() => Boolean(window.__E07_CANONICAL_FOCUS__), undefined, { timeout: 45_000 })
    await page
      .getByRole('button', { name: 'Bots', exact: true })
      .or(page.getByRole('tab', { name: 'Bots', exact: true }))
      .first()
      .click()
    const scout = page.locator('[data-slot="bots-roster"] [data-roster-key="local::scout"]')
    await expect(scout).toBeVisible()
    const oldFocus = await focus(page)
    expect(oldFocus.id).not.toBe(tip)
    const from = wire.length
    fs.writeFileSync(path.join(control, 'armed'), '', { flag: 'wx', mode: 0o600 })
    await scout.click()
    const viewport = page.locator('[data-slot="aui_thread-viewport"]').filter({ visible: true }).first()
    for (const marker of [rootMarker, tipMarker]) {
      const message = viewport.getByText(marker, { exact: true })
      await expect(message).toBeVisible({ timeout: 35_000 })
      await expect(message).toHaveCount(1)
    }
    await expect(viewport.getByText(defaultMarker, { exact: true })).toHaveCount(0)
    await expect.poll(() => focus(page)).toEqual({ id: tip, owner: { connectionId: 'local', profile } })
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
      expect(sockets.get(frame)).toMatchObject({ savedToken: false })
    }
    const historyReads = fs
      .readFileSync(path.join(control, 'rest.jsonl'), 'utf8')
      .split('\n')
      .filter(Boolean)
      .map(line => JSON.parse(line) as HistoryRead)
    expect(historyReads).toContainEqual({
      id: tip,
      scoped: true,
      includesCompacted: true,
      status: 200,
      targetMatches: true,
      orderedMarkers: true,
      rootMarkers: 1,
      tipMarkers: 1,
      decoyMarkers: 0
    })
    expect(historyReads.every(entry => entry.id === tip && entry.scoped)).toBe(true)
    expect(wire.filter(frame => ['session.create', 'prompt.submit'].includes(frame.method))).toEqual([])
    expect(chats()).toEqual(historyBefore)
    expect(inspect()).toEqual(after)
    expect(readEndpoint(gateway, profile)).toEqual(endpoint)
    expect(provider.completions.length).toBe(0)
    completed = true
  } finally {
    await app?.close().catch(() => undefined)
    const stopped = await Promise.allSettled(gateway ? [stopGateway(gateway)] : [])
    await provider.close()
    const live = sandboxProcesses(box)
    box.cleanup()
    if (completed) {
      expect(stopped.every(result => result.status === 'fulfilled')).toBe(true)
      expect(live).toHaveLength(0)
    }
  }
})
