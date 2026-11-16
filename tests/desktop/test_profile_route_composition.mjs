import assert from 'node:assert/strict'
import { readFileSync, realpathSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { extname, sep } from 'node:path'
import { after, test } from 'node:test'
import { pathToFileURL } from 'node:url'

const checkout = process.env.HERMES_DESKTOP_CHECKOUT
assert.ok(checkout, 'HERMES_DESKTOP_CHECKOUT must point to the verified Hermes checkout')
const upstream = pathToFileURL(`${realpathSync(checkout)}${sep}`).href
const desktop = `${upstream}apps/desktop/`
const shared = `${upstream}apps/shared/`
const lock = JSON.parse(readFileSync(new URL('pm/lock.json', upstream), 'utf8'))
assert.equal(process.versions.node, lock.packages.node.version, 'Use the pinned Hermes Node version')

const alias = 'research'
const local = { id: 'local', kind: 'local', label: 'This Device' }
const north = {
  id: 'north', kind: 'ssh', label: 'North', remoteProfile: 'backend-north', token: 'synthetic-token'
}
const south = { id: 'south', kind: 'ssh', label: 'South', remoteProfile: 'backend-south' }
const sources = [local, north, south]
const connected = [
  { connection: north, profiles: [alias], installId: 'synthetic-install-north' },
  { connection: south, profiles: [alias], installId: 'synthetic-install-south' }
]
const requestModule = `${desktop}src/sdk/profile-request.ts`
const botModule = `${desktop}src/plugins/hermes-bots/routing.ts`

let fixture
const bridgeName = 'hermes-superagent:desktop-profile-route-fixture'
const bridgeKey = Symbol.for(bridgeName)
const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
assert.equal(globalThis[bridgeKey], undefined)

function recordRequest(boundary, args) {
  fixture.calls.push({ boundary, args })
}

const bridge = {
  gateway: {
    async requestGatewayForAgent(...args) {
      recordRequest('gateway', args)
      const [connectionId, profile] = args
      const endpoint = fixture.endpoints.get(`${connectionId}/${profile}`)
      if (!endpoint) {
        throw new Error(`Fixture backend unavailable: ${connectionId}/${profile}`)
      }
      return endpoint
    },
    requestGatewayForProfile(...args) {
      recordRequest('profile-only gateway', args)
      assert.fail('Unexpected profile-only gateway request')
    }
  },
  profile: { get: () => fixture.cachedProfiles },
  host: {
    request(...args) {
      recordRequest('ambient gateway', args)
      assert.fail('Unexpected ambient gateway request')
    }
  }
}
globalThis[bridgeKey] = bridge
globalThis.window = {
  hermesDesktop: {
    async getAgentRoster() {
      return { agents: [], sources: fixture.sources }
    },
    async getProfileRoutes(names) {
      fixture.inventoryReads.push(names)
      return fixture.currentRoutes
    }
  }
}
after(() => {
  delete globalThis[bridgeKey]
  if (originalWindow) {
    Object.defineProperty(globalThis, 'window', originalWindow)
  } else {
    delete globalThis.window
  }
})

// Bind only the SDK's store imports and the Bot plugin's host facade. Every
// registry, alias, and request decision executes the pinned upstream source.
const fixtureExpression = `globalThis[Symbol.for(${JSON.stringify(bridgeName)})]`
const substitutions = new Map([
  [
    '@/store/gateway',
    [requestModule, `export const { requestGatewayForAgent, requestGatewayForProfile } = ${fixtureExpression}.gateway`]
  ],
  ['@/store/profile', [requestModule, `export const $profiles = ${fixtureExpression}.profile`]],
  ['@hermes/plugin-sdk', [botModule, `export const host = ${fixtureExpression}.host`]]
])

async function loadUpstream() {
  const hooks = registerHooks({
    resolve(specifier, context, nextResolve) {
      const substitution = substitutions.get(specifier)
      if (substitution) {
        const [importer, source] = substitution
        assert.equal(context.parentURL, importer, `Unexpected importer for ${specifier}`)
        return { shortCircuit: true, url: `data:text/javascript,${encodeURIComponent(source)}` }
      }
      try {
        return nextResolve(specifier, context)
      } catch (error) {
        // Resolve the extensionless TypeScript imports normally handled by
        // the Desktop bundler, solely within the pinned source directories.
        if (
          error.code !== 'ERR_MODULE_NOT_FOUND' ||
          !context.parentURL?.startsWith(upstream) ||
          (!specifier.startsWith('./') && !specifier.startsWith('../')) ||
          extname(specifier)
        ) {
          throw error
        }
        const candidate = new URL(`${specifier}.ts`, context.parentURL).href
        if (!candidate.startsWith(desktop) && !candidate.startsWith(shared)) {
          throw error
        }
        return nextResolve(candidate, context)
      }
    }
  })
  try {
    const registry = await import(`${desktop}electron/connection-registry.ts`)
    const descriptors = await import(`${desktop}electron/plugin-profile-routes.ts`)
    const sdk = await import(requestModule)
    bridge.host.requestProfile = sdk.requestPluginProfile
    const bots = await import(botModule)
    return {
      buildAgentRoster: registry.buildAgentRoster,
      rememberSshEnumeration: registry.rememberSshEnumeration,
      buildRegistryProfileRoutes: descriptors.buildRegistryProfileRoutes,
      pluginRouteStillRegistered: sdk.pluginRouteStillRegistered,
      requestPluginProfile: sdk.requestPluginProfile,
      requestForBot: bots.requestForBot
    }
  } finally {
    hooks.deregister()
  }
}

const {
  buildAgentRoster,
  rememberSshEnumeration,
  buildRegistryProfileRoutes,
  pluginRouteStillRegistered,
  requestPluginProfile,
  requestForBot
} = await loadUpstream()

function useFixture(context) {
  assert.equal(fixture, undefined)
  fixture = {
    calls: [],
    cachedProfiles: [{ name: alias }],
    currentRoutes: [],
    endpoints: new Map([
      ['north/research', { canonicalRoot: 'synthetic-root-north' }],
      ['south/research', { canonicalRoot: 'synthetic-root-south' }]
    ]),
    inventoryReads: [],
    sources
  }
  context.after(() => { fixture = undefined })
  return fixture
}

function buildRoutes(enumerations, registrySources = sources, primaryConnectionId = north.id) {
  const agents = buildAgentRoster(enumerations, { primaryConnectionId })
  return buildRegistryProfileRoutes({ agents, primaryConnectionId, sources: registrySources })
}

function requestBotRoster(route) {
  return requestForBot({ route, sourceScoped: true }, 'profiles.list', { profile: alias, include_sessions: true })
}

test('connected same-name routes preserve the source-local dial and backend operand', async context => {
  const state = useFixture(context)
  const roster = buildAgentRoster(connected, { primaryConnectionId: north.id })
  assert.deepEqual(roster.map(row => row.handle), ['research-north', 'research-south'])

  const routes = buildRoutes(connected)
  assert.deepEqual(routes, [
    { connectionId: 'north', mode: 'remote', primary: true, profile: alias, targetProfile: 'backend-north' },
    { connectionId: 'south', mode: 'remote', profile: alias, targetProfile: 'backend-south' }
  ])
  assert.deepEqual(await Promise.all(routes.map(requestBotRoster)), [
    { canonicalRoot: 'synthetic-root-north' },
    { canonicalRoot: 'synthetic-root-south' }
  ])

  const params = { profile: alias, include_sessions: false }
  await requestPluginProfile(routes[0], 'profiles.list', params)
  assert.deepEqual(state.calls, [
    { boundary: 'gateway', args: ['north', alias, 'profiles.list', { profile: 'backend-north', include_sessions: true }] },
    { boundary: 'gateway', args: ['south', alias, 'profiles.list', { profile: 'backend-south', include_sessions: true }] },
    { boundary: 'gateway', args: ['north', alias, 'profiles.list', { profile: alias, include_sessions: false }] }
  ])
})

test('cached and undialed SSH inventory retain their own locators without proving reachability', async context => {
  const state = useFixture(context)
  const failure = { profiles: null, error: 'fixture source offline' }
  const cached = rememberSshEnumeration(failure, [alias], north.kind)
  assert.deepEqual(cached, { profiles: [alias], error: failure.error })
  const cold = rememberSshEnumeration({ profiles: null, error: 'connect-on-demand' }, undefined, south.kind)
  assert.deepEqual(cold, { profiles: ['default'], error: 'connect-on-demand' })

  const [cachedRoute, coldRoute] = buildRoutes([
    { connection: north, ...cached }, { connection: south, ...cold }
  ])
  assert.deepEqual(cachedRoute, {
    connectionId: 'north', mode: 'remote', primary: true, profile: alias, targetProfile: 'backend-north'
  })
  assert.deepEqual(coldRoute, {
    connectionId: 'south', mode: 'remote', profile: 'default', targetProfile: 'backend-south'
  })
  state.endpoints.delete('north/research')
  await assert.rejects(requestBotRoster(cachedRoute), /Fixture backend unavailable: north\/research/)
  await assert.rejects(
    requestForBot({ route: coldRoute, sourceScoped: true }, 'profiles.list', { profile: 'default' }),
    /Fixture backend unavailable: south\/default/
  )
  assert.deepEqual(state.calls, [
    { boundary: 'gateway', args: ['north', alias, 'profiles.list', { profile: 'backend-north', include_sessions: true }] },
    { boundary: 'gateway', args: ['south', 'default', 'profiles.list', { profile: 'backend-south' }] }
  ])
})

test('incomplete descriptors and an ambiguous bare profile stop before routing', async context => {
  const state = useFixture(context)
  const [route] = buildRoutes(connected)
  for (const field of ['connectionId', 'profile', 'targetProfile']) {
    await assert.rejects(
      requestPluginProfile({ ...route, [field]: ' ' }, 'profiles.list', {}),
      /Profile route must include connectionId, profile, and targetProfile/
    )
  }
  await assert.rejects(requestPluginProfile(alias, 'profiles.list', {}), /requires a route descriptor/)
  assert.deepEqual(state.calls, [])
})

test('retry registration rejects replaced or removed routes while an explicit request never substitutes a twin', async context => {
  const state = useFixture(context)
  const [route, twin] = buildRoutes(connected)
  state.currentRoutes = [route, twin]
  assert.equal(await pluginRouteStillRegistered(route), true)

  const replacement = { ...north, remoteProfile: 'replacement-backend' }
  state.currentRoutes = buildRoutes([
    { ...connected[0], connection: replacement }, connected[1]
  ], [local, replacement, south])
  assert.deepEqual(state.currentRoutes[0], { ...route, targetProfile: 'replacement-backend' })
  assert.equal(await pluginRouteStillRegistered(route), false)

  state.sources = [local, south]
  state.currentRoutes = buildRoutes([connected[1]], state.sources, south.id)
  state.endpoints.delete('north/research')
  assert.equal(await pluginRouteStillRegistered(route), false)
  assert.deepEqual(state.inventoryReads, [[alias], [alias], [alias]])
  assert.deepEqual(state.calls, [])

  await assert.rejects(requestPluginProfile(route, 'profiles.list', {}), /Fixture backend unavailable: north\/research/)
  assert.deepEqual(state.calls, [{ boundary: 'gateway', args: ['north', alias, 'profiles.list', {}] }])
})

test('a copied install marker collapses registry rows and cannot distinguish separate endpoints', () => {
  const missing = connected.map(({ connection, profiles }) => ({ connection, profiles }))
  assert.equal(buildRoutes(missing).length, 2)

  const copied = connected.map(row => ({ ...row, installId: 'synthetic-copied-marker' }))
  const roster = buildAgentRoster(copied, { primaryConnectionId: south.id })
  assert.deepEqual(roster.map(row => [row.connectionId, row.handle]), [['south', alias]])
  assert.deepEqual(buildRoutes(copied, sources, south.id), [
    { connectionId: 'south', mode: 'remote', primary: true, profile: alias, targetProfile: 'backend-south' }
  ])
})
