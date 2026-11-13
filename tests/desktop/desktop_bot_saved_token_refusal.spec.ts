/** Overlay in the pinned Hermes apps/desktop/e2e/core directory. */
import * as fs from 'node:fs'
import * as path from 'node:path'

import { expect, type ElectronApplication, test } from '@playwright/test'

import { launchBotDesktop } from './desktop_bot_appimage'
import {
  focus,
  installCanonicalObserver,
  lookup,
  observeWire,
  phaseFor,
  readAudit,
  storedChats
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
import { composer, createCoreSandbox, freePort, sandboxProcesses } from './harness'
import { startScriptedProvider } from './provider'

const fixtureModule = 'apps.desktop.e2e.core.desktop_bot_canonical_fixture'
const source = 'spare'
const profile = 'scout'
const title = 'Bot Chat'
const canonical = 'fixture-canonical-scout'
const decoys = ['fixture-canonical-default', 'fixture-decoy-default', 'fixture-decoy-scout']
const selectors = { profile, title, includeHidden: true, limit: 200 }
const openMethods = new Set(['session.resume', 'session.activate'])
const writeMethods = new Set(['session.create', 'prompt.submit'])
const expectedIds = [[canonical, canonical]]

function auditControl(root: string) {
  const control = path.join(root, 'bot-canonical')
  fs.mkdirSync(control, { mode: 0o700 })
  fs.writeFileSync(path.join(control, 'wire.jsonl'), '', { mode: 0o600 })

  return control
}

test('Bot Mode checks the named canonical chat on the saved Webapp token route', async () => {
  test.setTimeout(200_000)
  expect(process.platform).toBe('linux')
  expect(path.isAbsolute(process.env.HERMES_E2E_PYTHON ?? '')).toBe(true)
  expect(process.env.HERMES_E2E_CORE_ROOT).toBeTruthy()
  const expectation = process.env.HERMES_E2E_BOT_WEBAPP_EXPECTATION ?? 'baseline'
  expect(['baseline', 'proposal']).toContain(expectation)
  const proposal = expectation === 'proposal'

  const provider = await startScriptedProvider()
  const localBox = createCoreSandbox('a')
  const remoteBox = createCoreSandbox('b')
  const gateways: Gateway[] = []
  let app: ElectronApplication | undefined
  let completed = false
  try {
    const localEnv = privateEnv(localBox)
    const remoteEnv = privateEnv(remoteBox)
    const localControl = auditControl(localBox.root)
    const remoteControl = auditControl(remoteBox.root)
    const webappPort = await freePort()
    seedInstall(localBox, localEnv, provider.url, profile, 'decoy', '4'.repeat(32))
    seedInstall(remoteBox, remoteEnv, provider.url, profile, 'canonical', '5'.repeat(32), webappPort)
    for (const box of [localBox, remoteBox]) {
      expect(Buffer.byteLength(path.join(box.hermesHome, 'gateway.sock'))).toBeLessThan(104)
    }
    installCanonicalObserver(localBox.hermesHome)
    const local = startGateway(localBox, { ...localEnv, HERMES_BOT_CANONICAL_CONTROL: localControl }, [
      '-m',
      fixtureModule
    ])
    gateways.push(local)
    const remote = startGateway(
      remoteBox,
      { ...remoteEnv, HERMES_BOT_CANONICAL_CONTROL: remoteControl, HERMES_BOT_CANONICAL_TRANSPORT: 'saved-token' },
      ['-m', fixtureModule]
    )
    gateways.push(remote)
    const [localEndpoint, remoteEndpoint] = await Promise.all([
      waitForEndpoint(local, profile),
      waitForEndpoint(remote, profile)
    ])
    expect(localEndpoint.instanceId).not.toBe(remoteEndpoint.instanceId)
    expect(localEndpoint.origin).not.toBe(remoteEndpoint.origin)
    expect(remoteEndpoint.origin).toBe(`http://127.0.0.1:${webappPort}`)
    const port = new URL(remoteEndpoint.origin).port
    runPython(remoteEnv, `import asyncio; from ${fixtureModule} import warm_canonical; asyncio.run(warm_canonical())`)

    const token = fs.readFileSync(path.join(remoteBox.hermesHome, 'webapp', 'session-token'), 'utf8').trim()
    expect(/^[A-Za-z0-9_-]{43}$/.test(token), 'native test Webapp token is available').toBe(true)
    fs.writeFileSync(
      path.join(localBox.userDataDir, 'connections.json'),
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
    fs.writeFileSync(
      path.join(localBox.userDataDir, 'active-profile.json'),
      JSON.stringify({ profile, connectionProfiles: { [source]: profile } }),
      { mode: 0o600 }
    )

    const live = await launchBotDesktop(localEnv)
    app = live.app
    const { page } = live
    const wire = observeWire(page)
    // Observe the primary dial even if Electron opened the first socket before firstWindow returned.
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(composer(page)).toBeVisible({ timeout: 45_000 })
    await expect
      .poll(() => page.evaluate(() => window.__E07_CANONICAL_ROUTE__?.()), { timeout: 45_000 })
      .toEqual({ connectionId: source, profile, gateway: 'open' })
    await page
      .getByRole('button', { name: 'Bots', exact: true })
      .or(page.getByRole('tab', { name: 'Bots', exact: true }))
      .first()
      .click()
    const roster = page.locator('[data-slot="bots-roster"]')
    const row = roster.locator(`[data-roster-key="${source}::${profile}"]`)
    await expect(row).toContainText(canonical)
    await expect(roster.locator('[data-roster-key="local::scout"]')).toBeVisible()
    const viewport = page.locator('[data-slot="aui_thread-viewport"]').filter({ visible: true }).first()
    const chatMarker = (id: string) => viewport.getByText(id, { exact: true })
    const failedToast = page.getByRole('alert').filter({ hasText: /Could not open .*’s chat/ })
    const beforeFocus = await focus(page)
    expect(beforeFocus.id).not.toBe(canonical)
    const snapshots = () => [localBox, remoteBox].map(box => storedChats(box.hermesHome, profile))
    const before = snapshots()
    expect(before.map(install => install.map(store => store.sessions.map(row => row.id)))).toEqual([
      [[decoys[1]], [decoys[2]]],
      [[decoys[0]], [canonical]]
    ])
    expect(before.flat().every(store => store.admissions.length === 0)).toBe(true)

    const from = wire.length
    phaseFor(localControl, 'empty', false)
    phaseFor(remoteControl, 'empty')
    await expect(failedToast).toHaveCount(0)
    await row.click()
    if (proposal) {
      await expect(failedToast).toBeVisible()
      await expect(failedToast).toContainText('Try again.')
      await expect(row).not.toHaveAttribute('aria-busy', 'true')
      await failedToast.getByRole('button', { name: 'Dismiss notification', exact: true }).click()
      await expect(failedToast).toHaveCount(0)
      expect(await focus(page)).toEqual(beforeFocus)
      await expect(chatMarker(canonical)).toHaveCount(0)
    } else {
      await expect(chatMarker(canonical)).toBeVisible({ timeout: 45_000 })
      await expect.poll(() => focus(page)).toEqual({ id: canonical, owner: { connectionId: source, profile } })
      await expect(failedToast).toHaveCount(0)
    }

    expect(JSON.parse(fs.readFileSync(path.join(remoteControl, 'fired-empty.json'), 'utf8'))).toEqual(expectedIds)
    const first = readAudit(remoteControl, 'empty')
    const canonicalRequests = first.filter(
      frame => (lookup(frame) || frame.method === 'session.info') && frame.direction === 'request'
    )
    const infoRequest = { method: 'session.info', sessionId: canonical, profile: proposal ? profile : null }
    const listRequest = { method: 'session.list', ...selectors, sessionId: null }
    expect(canonicalRequests).toEqual(
      (proposal ? [listRequest, infoRequest] : [listRequest, infoRequest, listRequest]).map(frame =>
        expect.objectContaining(frame)
      )
    )
    expect(first.filter(frame => frame.direction === 'reply' && lookup(frame))).toEqual(
      (proposal ? [[]] : [[], expectedIds]).map(ids => expect.objectContaining({ code: null, reason: null, ids }))
    )
    expect(first.filter(frame => frame.direction === 'handler')).toEqual([
      {
        direction: 'handler',
        phase: 'empty',
        method: 'session.info',
        sessionId: canonical,
        handlerAuthority: proposal ? profile : 'default',
        savedToken: true,
        hostScoped: true
      }
    ])
    expect(first.filter(frame => frame.direction === 'reply' && frame.method === 'session.info')).toEqual([
      expect.objectContaining(
        proposal
          ? {
              sessionId: canonical,
              code: null,
              reason: null,
              storedTitle: title,
              archived: false,
              profileName: profile
            }
          : { sessionId: canonical, code: 4001, reason: 'not_found' }
      )
    ])
    expect(wire.slice(from).filter(frame => lookup(frame) || frame.method === 'session.info')).toEqual(
      canonicalRequests.map(frame =>
        expect.objectContaining({
          port,
          method: frame.method,
          profile: frame.profile ?? undefined,
          sessionId: frame.sessionId ?? undefined,
          reply: frame.method === 'session.info' && !proposal ? { code: 4001, reason: 'not_found' } : {}
        })
      )
    )

    const checkOpens = (audit: ReturnType<typeof readAudit>, from: number, opens: boolean) => {
      const serverOpens = audit.filter(frame => openMethods.has(frame.method))
      const rendererOpens = wire.slice(from).filter(frame => openMethods.has(frame.method))
      expect(serverOpens.length > 0).toBe(opens)
      expect(rendererOpens.length > 0).toBe(opens)
      expect(serverOpens.every(frame => frame.profile === profile && frame.sessionId === canonical)).toBe(true)
      expect(
        rendererOpens.every(frame => frame.port === port && frame.profile === profile && frame.sessionId === canonical)
      ).toBe(true)
    }
    checkOpens(first, from, !proposal)
    expect(first.filter(frame => writeMethods.has(frame.method))).toEqual([])
    expect(
      readAudit(localControl, 'empty').filter(
        frame =>
          lookup(frame) ||
          frame.method === 'session.info' ||
          openMethods.has(frame.method) ||
          writeMethods.has(frame.method)
      )
    ).toEqual([])
    expect(wire.slice(from).filter(frame => writeMethods.has(frame.method))).toEqual([])
    expect(snapshots()).toEqual(before)

    if (proposal) {
      const retryFrom = wire.length
      phaseFor(localControl, 'retry')
      phaseFor(remoteControl, 'retry')
      await row.click()
      await expect(chatMarker(canonical)).toBeVisible({ timeout: 45_000 })
      await expect.poll(() => focus(page)).toEqual({ id: canonical, owner: { connectionId: source, profile } })
      const retry = readAudit(remoteControl, 'retry')
      expect(retry.filter(frame => frame.direction === 'request' && lookup(frame))).toEqual([
        expect.objectContaining(listRequest)
      ])
      expect(retry.filter(frame => frame.direction === 'reply' && lookup(frame))).toEqual([
        expect.objectContaining({ code: null, reason: null, ids: expectedIds })
      ])
      expect(retry.filter(frame => frame.method === 'session.info' || writeMethods.has(frame.method))).toEqual([])
      expect(wire.slice(retryFrom).filter(frame => lookup(frame) || frame.method === 'session.info')).toEqual([
        expect.objectContaining({ port, method: 'session.list', ...selectors, reply: {} })
      ])
      expect(wire.slice(retryFrom).filter(frame => writeMethods.has(frame.method))).toEqual([])
      expect(
        readAudit(localControl, 'retry').filter(
          frame =>
            lookup(frame) ||
            frame.method === 'session.info' ||
            openMethods.has(frame.method) ||
            writeMethods.has(frame.method)
        )
      ).toEqual([])
      checkOpens(retry, retryFrom, true)
      expect(snapshots()).toEqual(before)
    }
    for (const id of decoys) {
      await expect(chatMarker(id!)).toHaveCount(0)
    }
    expect(provider.completions.length).toBe(0)
    expect(readEndpoint(local, profile)).toEqual(localEndpoint)
    expect(readEndpoint(remote, profile)).toEqual(remoteEndpoint)
    completed = true
  } finally {
    await app?.close().catch(() => undefined)
    const stopped = await Promise.allSettled(gateways.map(stopGateway))
    await provider.close()
    for (const box of [localBox, remoteBox]) {
      const live = sandboxProcesses(box)
      box.cleanup()
      if (completed) {
        expect(live.length, 'no fixture processes remain').toBe(0)
      }
    }
    if (completed) {
      expect(
        stopped.every(result => result.status === 'fulfilled'),
        'both owned Gateways stop'
      ).toBe(true)
    }
  }
})
