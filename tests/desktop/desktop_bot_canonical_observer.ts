/** Read-only UI and owner audit helpers for the pinned Hermes Bot Mode overlays. */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { DatabaseSync } from 'node:sqlite'

import { type Page } from '@playwright/test'

const title = 'Bot Chat'

export type Phase = 'refusal' | 'empty' | 'retry'
export interface WireFrame {
  port: string
  method: string
  profile?: string
  sessionId?: string
  title?: string
  includeHidden?: boolean
  limit?: number
  reply?: { code?: number; reason?: string }
}

export interface AuditFrame {
  phase: Phase
  direction: 'request' | 'reply' | 'handler'
  method: string
  profile?: string | null
  sessionId?: string | null
  title?: string | null
  includeHidden?: boolean | null
  limit?: number | null
  code?: number | null
  reason?: string | null
  ids?: string[][]
  storedTitle?: string | null
  archived?: boolean | null
  profileName?: string | null
  targetAuthority?: boolean
  handlerAuthority?: 'default' | 'scout' | 'other'
  savedToken?: boolean
  hostScoped?: boolean
}

interface Focus {
  id: string | null
  owner: { connectionId: string; profile: string } | null
}

declare global {
  interface Window {
    __E07_CANONICAL_FOCUS__?: () => Focus
    __E07_CANONICAL_ROUTE__?: () => { connectionId: string | null; profile: string; gateway: string }
  }
}

export function observeWire(page: Page): WireFrame[] {
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

export function readAudit(control: string, phase: Phase): AuditFrame[] {
  return fs
    .readFileSync(path.join(control, 'wire.jsonl'), 'utf8')
    .split('\n')
    .filter(Boolean)
    .map(line => JSON.parse(line) as AuditFrame)
    .filter(frame => frame.phase === phase)
}

export function phaseFor(control: string, phase: Phase, arm = phase !== 'retry') {
  const temp = path.join(control, 'phase.new')
  fs.writeFileSync(temp, phase, { mode: 0o600 })
  fs.renameSync(temp, path.join(control, 'phase'))
  if (arm) {
    fs.writeFileSync(path.join(control, `arm-${phase}`), '', { flag: 'wx', mode: 0o600 })
  }
}

export function storedChats(home: string, profile: string) {
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

export function focus(page: Page) {
  return page.evaluate(() => window.__E07_CANONICAL_FOCUS__!())
}

export function lookup(frame: WireFrame | AuditFrame) {
  return frame.method === 'session.list' && frame.title === title
}

export function installCanonicalObserver(home: string) {
  const plugin = path.join(home, 'desktop-plugins', 'e07-canonical-observer')
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
    globalThis.__E07_CANONICAL_ROUTE__ = () => ({
      connectionId: host.state.connectionId.get(),
      profile: host.state.profile.get(),
      gateway: host.state.gateway.get()
    })
  }
}
`
  )
}
