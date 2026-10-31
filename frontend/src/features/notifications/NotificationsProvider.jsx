import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, session, wsUrl } from '../../lib/api'
import { useToast } from '../../components/ui'
import { useAuth } from '../auth/AuthContext'

const NONE = { connected: false, presence: {}, typing: {}, incomingCall: null, lastCallEnd: null, sendTyping: () => {}, dismissCall: () => {} }
const Ctx = createContext(NONE)
export const useRealtime = () => useContext(Ctx)

const TYPING_MS = 4500

/** One WebSocket per session. Auth is sent as the first message so tokens never appear in URLs/logs.
 *  Besides refreshing data, it keeps the short-lived chat state (who is online, who is typing) and any incoming call. */
export function NotificationsProvider({ children }) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [connected, setConnected] = useState(false)
  const [presence, setPresence] = useState({})   // userId -> { online, last_seen_at }
  const [typing, setTyping] = useState({})       // conversationId -> { userId -> { name, until } }
  const [incomingCall, setIncomingCall] = useState(null) // { room_id, from_id, from_name, video }
  const [lastCallEnd, setLastCallEnd] = useState(null)   // { room_id, outcome, at }
  const alive = useRef(true)
  const wsRef = useRef(null)
  const lastTyping = useRef(0)
  const seen = useRef(new Set())

  const sendTyping = useCallback((conversationId) => {
    const now = Date.now()
    if (now - lastTyping.current < 2000 || wsRef.current?.readyState !== 1) return
    lastTyping.current = now
    wsRef.current.send(JSON.stringify({ type: 'typing', conversation_id: conversationId }))
  }, [])
  const dismissCall = useCallback(() => setIncomingCall(null), [])

  useEffect(() => {
    const id = setInterval(() => setTyping((t) => {
      const now = Date.now()
      let changed = false
      const next = {}
      for (const [cid, people] of Object.entries(t)) {
        const alive_ = Object.fromEntries(Object.entries(people).filter(([, v]) => v.until > now))
        if (Object.keys(alive_).length !== Object.keys(people).length) changed = true
        if (Object.keys(alive_).length) next[cid] = alive_
      }
      return changed ? next : t
    }), 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (!user || user.role === 'platform_admin') return undefined
    alive.current = true
    let ws, retry = 0, timer, ping

    const refreshData = () => qc.invalidateQueries({ predicate: (q) => /^\/(notifications|dashboard)/.test(q.queryKey[0]) })
    const refreshChat = () => qc.invalidateQueries({ predicate: (q) => /^\/chat/.test(q.queryKey[0]) })

    const connect = () => {
      if (!session.exists()) return
      ws = new WebSocket(wsUrl('/ws'))
      wsRef.current = ws
      ws.onopen = () => ws.send(JSON.stringify({ type: 'auth' }))
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data)
        const d = msg.data
        if (msg.type === 'ready') {
          retry = 0; setConnected(true)
          ping = setInterval(() => ws.readyState === 1 && ws.send('{"type":"ping"}'), 30000)
          refreshChat() // anything missed while offline
          // messages that arrived while this device was offline are delivered now: acknowledge them so the sender's ticks move on
          api.get('/chat/conversations').then((r) => r.items.forEach((c) => {
            const last = c.last_message, mine = c.members.find((m) => m.id === user.id)
            if (last && !last.deleted && last.sender_id !== user.id && mine && mine.last_delivered_id < last.id && ws.readyState === 1) {
              ws.send(JSON.stringify({ type: 'ack', conversation_id: c.id, message_id: last.id }))
            }
          })).catch(() => {})
          api.get('/chat/presence').then((r) => setPresence(Object.fromEntries(r.items.map((p) => [p.user_id, { online: p.online, last_seen_at: p.last_seen_at }])))).catch(() => {})
        } else if (msg.type === 'notification') {
          toast(`${d.title}${d.body ? ` — ${d.body}` : ''}`)
          refreshData()
        } else if (msg.type === 'chat') {
          refreshChat()
          // tell the sender this device has the message; `seen` stops a repeated push from being acknowledged twice
          if (d.sender_id !== user.id && !d.deleted && !seen.current.has(`${d.id}:${d.edited_at || ''}:${(d.reactions || []).length}`) && ws.readyState === 1) {
            seen.current.add(`${d.id}:${d.edited_at || ''}:${(d.reactions || []).length}`)
            if (seen.current.size > 500) seen.current = new Set([...seen.current].slice(-200))
            ws.send(JSON.stringify({ type: 'ack', conversation_id: d.conversation_id, message_id: d.id }))
          }
          if (d.sender_id !== user.id) setTyping((t) => { const c = { ...(t[d.conversation_id] || {}) }; delete c[d.sender_id]; return { ...t, [d.conversation_id]: c } })
        } else if (msg.type === 'chat_read' || msg.type === 'chat_delivered') {
          refreshChat()
        } else if (msg.type === 'chat_typing') {
          setTyping((t) => ({ ...t, [d.conversation_id]: { ...(t[d.conversation_id] || {}), [d.user_id]: { name: d.name, until: Date.now() + TYPING_MS } } }))
        } else if (msg.type === 'presence') {
          setPresence((p) => ({ ...p, [d.user_id]: { online: d.online, last_seen_at: d.last_seen_at } }))
        } else if (msg.type === 'call') {
          setIncomingCall({ ...d, at: Date.now() })
          setLastCallEnd(null)
        } else if (msg.type === 'call_ended') {
          setIncomingCall((c) => (c && c.room_id === d.room_id ? null : c))
          setLastCallEnd({ room_id: d.room_id, outcome: d.outcome, at: Date.now() })
          qc.invalidateQueries({ predicate: (q) => /^\/meetings/.test(q.queryKey[0]) })
        } else if (msg.type === 'event') {
          qc.invalidateQueries({ predicate: (q) => /^\/(projects|tasks|dashboard)/.test(q.queryKey[0]) })
        }
      }
      ws.onclose = async (e) => {
        clearInterval(ping); setConnected(false)
        if (!alive.current) return
        if (e.code === 4401) {
          session.clear()
          window.dispatchEvent(new Event('ws:logout'))
          return
        }
        timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** retry++))
      }
    }
    connect()
    return () => { alive.current = false; clearTimeout(timer); clearInterval(ping); ws?.close(); wsRef.current = null }
  }, [user, qc, toast])

  const value = useMemo(() => ({ connected, presence, typing, incomingCall, lastCallEnd, sendTyping, dismissCall }), [connected, presence, typing, incomingCall, lastCallEnd, sendTyping, dismissCall])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
