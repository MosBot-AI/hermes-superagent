/** Overlay in the pinned Hermes apps/desktop/e2e/core directory. */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { DatabaseSync } from 'node:sqlite'

import { expect, type ElectronApplication, type Page, test } from '@playwright/test'

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
import { composer, createCoreSandbox, launchCoreApp, sandboxProcesses } from './harness'
import { startScriptedProvider } from './provider'

const fixtureModule = 'apps.desktop.e2e.core.desktop_bot_canonical_fixture'
const profile = 'scout'
const title = 'Bot Chat'
const canonical = 'fixture-canonical-scout'
const side = 'fixture-canonical-side'
const defaultChat = 'fixture-canonical-default'
const selectors = { profile, title, includeHidden: true, limit: 200 }
const openMethods = new Set(['session.resume', 'session.activate'])
const writeMethods = new Set(['session.create', 'prompt.submit'])

type Phase = 'refusal' | 'empty' | 'retry'
interface WireFrame {
  port: string
  method: string
  profile?: string
  sessionId?: string
  title?: string
  includeHidden?: boolean
  limit?: number
  reply?: { code?: number; reason?: string }
}

interface AuditFrame {
  phase: Phase
  direction: 'request' | 'reply'
  method: string
  profile: string | null
  sessionId: string | null
  title: string | null
  includeHidden: boolean | null
  limit: number | null
  code?: number | null
  reason?: string | null
  ids?: string[][]
  storedTitle?: string | null
  archived?: boolean | null
  profileName?: string | null
  targetAuthority?: boolean
}

interface Focus {
  id: string | null
  owner: { connectionId: string; profile: string } | null
}

declare global {
  interface Window {
    __E07_CANONICAL_FOCUS__?: () => Focus
  }
}

function observeWire(page: Page): WireFrame[] {
  const frames: WireFrame[] = []
  page.on('websocket', socket => {
    const url = new URL(socket.url())
    if (url.pathname !== '/api/ws') {
      return
    }
    const pending = new Map<string, WireFrame>()
    socket.on('framesent', event => {
      try {
        const message = JSON.parse(String(event.payload))
        if (message?.id === undefined || typeof message.method !== 'string') {
          return
        }
        const { profile, session_id, title, include_hidden, limit } = message.params ?? {}
        const frame: WireFrame = {
          port: url.port,
          method: message.method,
          profile,
          sessionId: session_id,
          title,
          includeHidden: include_hidden,
          limit
        }
        frames.push(frame)
        pending.set(String(message.id), frame)
      } catch {
        // A non-JSON frame is not an RPC.
      }
    })
    socket.on('framereceived', event => {
      try {
        const message = JSON.parse(String(event.payload))
        const frame = pending.get(String(message?.id))
        if (frame) {
          frame.reply = { code: message.error?.code, reason: message.error?.data?.reason }
          pending.delete(String(message.id))
        }
      } catch {
        // A non-JSON frame is not an RPC response.
      }
    })
  })
  return frames
}

function readAudit(control: string, phase: Phase): AuditFrame[] {
  return fs
    .readFileSync(path.join(control, 'wire.jsonl'), 'utf8')
    .trim()
    .split('\n')
    .map(line => JSON.parse(line) as AuditFrame)
    .filter(frame => frame.phase === phase)
}

function phaseFor(control: string, phase: Phase) {
  const temp = path.join(control, 'phase.new')
  fs.writeFileSync(temp, phase, { mode: 0o600 })
  fs.renameSync(temp, path.join(control, 'phase'))
  if (phase !== 'retry') {
    fs.writeFileSync(path.join(control, `arm-${phase}`), '', { flag: 'wx', mode: 0o600 })
  }
}

function storedChats(home: string) {
  return [home, path.join(home, 'profiles', profile)].map(dir => {
    const db = new DatabaseSync(path.join(dir, 'state.db'), { readOnly: true })
    try {
      db.exec('BEGIN')
      return {
        sessions: db.prepare('SELECT id,title,hidden,parent_session_id FROM sessions ORDER BY id').all(),
        messages: db.prepare('SELECT id,session_id,role,content FROM messages ORDER BY id').all(),
        admissions: db
          .prepare('SELECT admission_id,request_id,status,outcome FROM session_admissions ORDER BY admission_id')
          .all()
      }
    } finally {
      db.close()
    }
  })
}

function focus(page: Page) {
  return page.evaluate(() => window.__E07_CANONICAL_FOCUS__!())
}

function lookup(frame: WireFrame | AuditFrame) {
  return frame.method === 'session.list' && frame.title === title
}

test('Bot Mode refuses uncertain canonical lookups then opens the existing chat', async () => {
  test.setTimeout(180_000)
  expect(process.platform).toBe('linux')
  expect(path.isAbsolute(process.env.HERMES_E2E_PYTHON ?? '')).toBe(true)
  expect(process.env.HERMES_E2E_CORE_ROOT).toBeTruthy()

  const provider = await startScriptedProvider()
  const box = createCoreSandbox('bot')
  let gateway: Gateway | undefined
  let app: ElectronApplication | undefined
  let completed = false
  try {
    const env = privateEnv(box)
    const control = path.join(box.root, 'bot-canonical')
    fs.mkdirSync(control, { mode: 0o700 })
    fs.writeFileSync(path.join(control, 'wire.jsonl'), '', { mode: 0o600 })
    seedInstall(box, env, provider.url, profile, 'canonical', '3'.repeat(32))
    runPython(env, `from ${fixtureModule} import seed_side; seed_side()`)
    expect(Buffer.byteLength(path.join(box.hermesHome, 'gateway.sock'))).toBeLessThan(104)
    const plugin = path.join(box.hermesHome, 'desktop-plugins', 'e07-canonical-observer')
    fs.mkdirSync(plugin, { recursive: true })
    fs.writeFileSync(
      path.join(plugin, 'plugin.js'),
      `
import { host } from '@hermes/plugin-sdk'
export default {
  id: 'e07-canonical-observer',
  register() {
    globalThis.__E07_CANONICAL_FOCUS__ = () => ({
      id: host.state.focusedStoredSessionId.get(),
      owner: host.state.focusedSessionOwner.get()
    })
  }
}
`
    )
    gateway = startGateway(box, { ...env, HERMES_BOT_CANONICAL_CONTROL: control }, ['-m', fixtureModule])
    const endpoint = await waitForEndpoint(gateway, profile)
    const port = new URL(endpoint.origin).port
    // Let the native named authority adopt the existing CLI-shaped seed before snapshots.
    runPython(env, `import asyncio; from ${fixtureModule} import warm_canonical; asyncio.run(warm_canonical())`)

    const live = await launchCoreApp(env)
    app = live.app
    const { page } = live
    const wire = observeWire(page)
    await page.waitForFunction(() => Boolean(window.__E07_CANONICAL_FOCUS__), undefined, { timeout: 45_000 })
    await expect(composer(page)).toBeVisible({ timeout: 45_000 })
    await page
      .getByRole('button', { name: 'Bots', exact: true })
      .or(page.getByRole('tab', { name: 'Bots', exact: true }))
      .first()
      .click()
    const row = page.locator('[data-slot="bots-roster"] [data-roster-key="local::scout"]')
    await expect(row).toBeVisible()
    // The row preview comes from the real roster and establishes the positive canonical pointer.
    await expect(row).toContainText(canonical)
    const viewport = page.locator('[data-slot="aui_thread-viewport"]').filter({ visible: true }).first()
    const chatMarker = (id: string) => viewport.getByText(id, { exact: true })
    const beforeFocus = await focus(page)
    expect(beforeFocus.id).not.toBe(canonical)
    const before = storedChats(box.hermesHome)
    expect(before[0]!.sessions).toEqual([{ id: defaultChat, title, hidden: 1, parent_session_id: null }])
    expect(before[1]!.sessions).toEqual([
      { id: canonical, title, hidden: 1, parent_session_id: null },
      { id: side, title: 'Side Thread', hidden: 0, parent_session_id: null }
    ])
    expect(before.map(item => item.admissions.length)).toEqual([0, 0])

    const failedToast = page.getByRole('alert').filter({ hasText: /Could not open .*’s chat/ })
    for (const phase of ['refusal', 'empty'] as const) {
      await expect(failedToast).toHaveCount(0)
      const from = wire.length
      phaseFor(control, phase)
      await row.click()
      await expect(failedToast).toBeVisible()
      await expect(failedToast).toContainText('Try again.')
      await expect(row).not.toHaveAttribute('aria-busy', 'true')
      await failedToast.getByRole('button', { name: 'Dismiss notification', exact: true }).click()
      await expect(failedToast).toHaveCount(0)
      expect(await focus(page)).toEqual(beforeFocus)
      for (const id of [canonical, side, defaultChat]) {
        await expect(chatMarker(id)).toHaveCount(0)
      }
      const expectedFailure = phase === 'refusal'
      const browserLookups = wire.slice(from).filter(lookup)
      expect(browserLookups).toEqual([
        {
          port,
          method: 'session.list',
          ...selectors,
          sessionId: undefined,
          reply: expectedFailure ? { code: 4001, reason: 'permission_denied' } : {}
        }
      ])
      expect(JSON.parse(fs.readFileSync(path.join(control, `fired-${phase}.json`), 'utf8'))).toEqual([
        [canonical, canonical]
      ])
      const audit = readAudit(control, phase)
      expect(audit.filter(frame => frame.direction === 'request' && lookup(frame))).toEqual([
        { phase, direction: 'request', method: 'session.list', ...selectors, sessionId: null }
      ])
      const lookups = audit.filter(frame => frame.direction === 'reply' && lookup(frame))
      expect(lookups).toHaveLength(1)
      expect(lookups[0]).toMatchObject({
        code: expectedFailure ? 4001 : null,
        reason: expectedFailure ? 'permission_denied' : null,
        ids: []
      })
      const info = audit.filter(frame => frame.method === 'session.info' && frame.sessionId === canonical)
      if (expectedFailure) {
        expect(info).toEqual([])
      } else {
        expect(info).toHaveLength(2)
        expect(info[0]).toMatchObject({
          direction: 'request',
          profile: null,
          sessionId: canonical,
          targetAuthority: true
        })
        expect(info[1]).toMatchObject({
          direction: 'reply',
          sessionId: canonical,
          code: null,
          reason: null,
          storedTitle: title,
          archived: false,
          profileName: profile,
          targetAuthority: true
        })
        const rendererInfo = wire
          .slice(from)
          .filter(frame => frame.method === 'session.info' && frame.sessionId === canonical)
        expect(rendererInfo).toHaveLength(1)
        expect(rendererInfo[0]).toMatchObject({ port, profile: undefined, reply: {} })
      }
      expect(audit.filter(frame => openMethods.has(frame.method) || writeMethods.has(frame.method))).toEqual([])
      expect(wire.slice(from).filter(frame => openMethods.has(frame.method) || writeMethods.has(frame.method))).toEqual(
        []
      )
      expect(storedChats(box.hermesHome)).toEqual(before)
    }

    const from = wire.length
    phaseFor(control, 'retry')
    await row.click()
    await expect(chatMarker(canonical)).toBeVisible({ timeout: 45_000 })
    await expect.poll(() => focus(page)).toEqual({ id: canonical, owner: { connectionId: 'local', profile } })
    for (const id of [side, defaultChat]) {
      await expect(chatMarker(id)).toHaveCount(0)
    }
    const retry = readAudit(control, 'retry')
    expect(retry.filter(frame => frame.direction === 'request' && lookup(frame))).toEqual([
      { phase: 'retry', direction: 'request', method: 'session.list', ...selectors, sessionId: null }
    ])
    expect(retry.filter(frame => frame.direction === 'reply' && lookup(frame))).toEqual([
      expect.objectContaining({ ...selectors, code: null, reason: null, ids: [[canonical, canonical]] })
    ])
    const serverOpens = retry.filter(frame => openMethods.has(frame.method))
    const rendererOpens = wire.slice(from).filter(frame => openMethods.has(frame.method))
    expect(serverOpens).not.toHaveLength(0)
    expect(rendererOpens).not.toHaveLength(0)
    expect(serverOpens.every(frame => frame.profile === profile && frame.sessionId === canonical)).toBe(true)
    expect(
      rendererOpens.every(frame => frame.port === port && frame.profile === profile && frame.sessionId === canonical)
    ).toBe(true)
    expect(retry.filter(frame => writeMethods.has(frame.method))).toEqual([])
    expect(wire.slice(from).filter(frame => writeMethods.has(frame.method))).toEqual([])
    expect(storedChats(box.hermesHome)).toEqual(before)
    expect(provider.completions.length).toBe(0)
    expect(readEndpoint(gateway, profile)).toEqual(endpoint)
    completed = true
  } finally {
    await app?.close().catch(() => undefined)
    const stopped = await Promise.allSettled(gateway ? [stopGateway(gateway)] : [])
    await provider.close()
    const live = sandboxProcesses(box)
    box.cleanup()
    if (completed) {
      expect(
        stopped.every(result => result.status === 'fulfilled'),
        'the owned Gateway stops'
      ).toBe(true)
      expect(live.length, 'no fixture processes remain').toBe(0)
    }
  }
})
