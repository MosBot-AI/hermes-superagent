import { afterEach, expect, it, vi } from 'vitest'

import { requestForBot } from '@/plugins/hermes-bots/routing'
import {
  activeGateway,
  closeSecondaryGateways,
  disposeSecondariesForConnection,
  ensureGatewayForProfile,
  gatewayRouteState,
  retainGatewayForRelay,
  setPrimaryGateway,
  setPrimaryGatewayConnectionId
} from './gateway'
import { buildAgentRoster, type RegistryConnection } from '../../electron/connection-registry'
import { buildRegistryProfileRoutes, type OpaqueProfileRoute } from '../../electron/plugin-profile-routes'

const { FixtureGateway, ambientRequest, refuseNetwork } = vi.hoisted(() => {
  class FixtureGateway {
    connectionState: 'closed' | 'open' = 'closed'
    private wsUrl: string | undefined

    connect = vi.fn(async (wsUrl: string) => {
      this.wsUrl = wsUrl
      this.connectionState = 'open'
    })

    request = vi.fn(async (method: string, params: Record<string, unknown>) => {
      if (!this.wsUrl || this.connectionState !== 'open') {
        throw new Error('Fixture transport is closed')
      }
      return { endpoint: this.wsUrl, method, params }
    })

    close = vi.fn(() => {
      this.connectionState = 'closed'
    })
    onEvent = () => () => undefined
    onState = () => () => undefined
  }
  const ambientRequest = vi.fn(() => {
    throw new Error('Unexpected ambient SDK request')
  })
  const refuseNetwork = vi.fn(() => {
    throw new Error('Unexpected network access')
  })
  vi.stubGlobal('fetch', refuseNetwork)
  vi.stubGlobal('WebSocket', refuseNetwork)
  return { FixtureGateway, ambientRequest, refuseNetwork }
})

vi.mock('@/hermes', async importOriginal => ({
  ...(await importOriginal<typeof import('@/hermes')>()),
  HermesGateway: FixtureGateway
}))

// Keep the SDK request implementation and renderer pool live, without importing the entire UI facade.
vi.mock('@hermes/plugin-sdk', async () => {
  const { requestPluginProfile } = await import('@/sdk/profile-request')
  return { host: { request: ambientRequest, requestProfile: requestPluginProfile } }
})

const profile = 'research'
const connections: RegistryConnection[] = [
  { id: 'local', kind: 'local', label: 'This Device' },
  { id: 'north', kind: 'ssh', label: 'North', remoteProfile: 'backend-north' },
  { id: 'south', kind: 'ssh', label: 'South', remoteProfile: 'backend-south' }
]

function routesFor(sources: RegistryConnection[]) {
  const primaryConnectionId = 'local'
  const enumerations = sources.map(connection => ({ connection, profiles: [profile] }))
  const agents = buildAgentRoster(enumerations, { primaryConnectionId })
  return buildRegistryProfileRoutes({ agents, primaryConnectionId, sources })
}

function requestRoster(route: OpaqueProfileRoute) {
  return requestForBot({ route, sourceScoped: true }, 'profiles.list', { profile, include_sessions: true })
}

afterEach(async () => {
  try {
    closeSecondaryGateways()
    setPrimaryGateway(null)
    await ensureGatewayForProfile('default')
  } finally {
    vi.unstubAllGlobals()
  }
})

it('routes same-named Bot reads through distinct pooled sources and refuses a removed source', async () => {
  let routes = routesFor(connections)
  const north = routes.find(route => route.connectionId === 'north')!
  const south = routes.find(route => route.connectionId === 'south')!
  expect(north).toEqual({ connectionId: 'north', mode: 'remote', profile, targetProfile: 'backend-north' })
  expect(south).toEqual({ connectionId: 'south', mode: 'remote', profile, targetProfile: 'backend-south' })

  const wsUrlFor = (connectionId: string) => `wss://${connectionId}.invalid/api/ws`
  type Scope = { connectionId: string; profile: string }
  const getConnectionFor = vi.fn(async (scope: Scope) => {
    if (!routes.some(route => route.connectionId === scope.connectionId && route.profile === scope.profile)) {
      throw new Error(`No connection with id "${scope.connectionId}"`)
    }
    return { ...scope, mode: 'remote', wsUrl: `wss://${scope.connectionId}.invalid/cached` }
  })
  const getGatewayWsUrlFor = vi.fn(async ({ connectionId }: Scope) => wsUrlFor(connectionId))
  const getConnection = vi.fn(() => {
    throw new Error('Unexpected legacy connection lookup')
  })
  const getGatewayWsUrl = vi.fn(() => {
    throw new Error('Unexpected legacy WebSocket URL lookup')
  })
  vi.stubGlobal('hermesDesktop', { getConnectionFor, getGatewayWsUrlFor, getConnection, getGatewayWsUrl })

  const primary = new FixtureGateway()
  await primary.connect(wsUrlFor('local'))
  setPrimaryGateway(primary as unknown as Parameters<typeof setPrimaryGateway>[0], profile)
  setPrimaryGatewayConnectionId('local', 'local')
  await ensureGatewayForProfile(profile)

  // Retain both entries without opening them. The Bot requests make the actual pool dials.
  const releaseNorth = retainGatewayForRelay(north.connectionId, north.profile)
  const releaseSouth = retainGatewayForRelay(south.connectionId, south.profile)
  try {
    const scopeNorth = { connectionId: 'north', profile }
    const scopeSouth = { connectionId: 'south', profile }
    const requestNorth = { profile: 'backend-north', include_sessions: true }
    const requestSouth = { profile: 'backend-south', include_sessions: true }
    await expect(Promise.all([requestRoster(north), requestRoster(south)])).resolves.toEqual([
      { endpoint: wsUrlFor('north'), method: 'profiles.list', params: requestNorth },
      { endpoint: wsUrlFor('south'), method: 'profiles.list', params: requestSouth }
    ])
    const northGateway = gatewayRouteState('north', profile).gateway
    const southGateway = gatewayRouteState('south', profile).gateway
    expect(northGateway).not.toBeNull()
    expect(southGateway).not.toBeNull()
    expect(northGateway).not.toBe(southGateway)
    expect(getConnectionFor).toHaveBeenCalledTimes(2)
    expect(getConnectionFor).toHaveBeenCalledWith(scopeNorth)
    expect(getConnectionFor).toHaveBeenCalledWith(scopeSouth)
    expect(getGatewayWsUrlFor).toHaveBeenCalledTimes(2)
    expect(getGatewayWsUrlFor).toHaveBeenCalledWith(scopeNorth)
    expect(getGatewayWsUrlFor).toHaveBeenCalledWith(scopeSouth)

    routes = routesFor(connections.filter(connection => connection.id !== north.connectionId))
    disposeSecondariesForConnection(north.connectionId)
    expect(northGateway?.close).toHaveBeenCalledOnce()
    expect(gatewayRouteState('north', profile).open).toBe(false)
    await expect(requestRoster(north)).rejects.toThrow('No connection with id "north"')

    expect(getConnectionFor).toHaveBeenCalledTimes(3)
    expect(getConnectionFor).toHaveBeenLastCalledWith(scopeNorth)
    expect(getGatewayWsUrlFor).toHaveBeenCalledTimes(2)
    expect(northGateway?.request).toHaveBeenCalledExactlyOnceWith('profiles.list', requestNorth)
    expect(southGateway?.request).toHaveBeenCalledExactlyOnceWith('profiles.list', requestSouth)
    expect(gatewayRouteState('south', profile).gateway).toBe(southGateway)
    expect(activeGateway()).toBe(primary)
    expect(primary.request).not.toHaveBeenCalled()
    expect(ambientRequest).not.toHaveBeenCalled()
    expect(getConnection).not.toHaveBeenCalled()
    expect(getGatewayWsUrl).not.toHaveBeenCalled()
    expect(refuseNetwork).not.toHaveBeenCalled()
  } finally {
    releaseNorth()
    releaseSouth()
  }
})
