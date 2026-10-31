import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { Avatar } from '../../components/ui'
import { ROLE_LABEL } from '../../lib/format'
import { useApi } from '../../lib/hooks'
import { breadcrumbs, navFor } from '../../lib/nav'
import { useAuth } from '../auth/AuthContext'
import NotificationBell from '../notifications/NotificationBell'
import IncomingCall from '../meetings/IncomingCall'
import AccessDenied from './AccessDenied'

const ICONS = {
  home: 'M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10', check: 'M5 13l4 4L19 7', folder: 'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z',
  pencil: 'M4 20h4L19 9l-4-4L4 16v4z', users: 'M16 11a4 4 0 10-8 0 4 4 0 008 0zM4 20a8 8 0 0116 0', clock: 'M12 7v5l3 2M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2', calendar: 'M5 5h14v15H5zM5 10h14M9 3v4M15 3v4', inbox: 'M4 13l2-8h12l2 8M4 13v6h16v-6M4 13h5l1 2h4l1-2h5',
  building: 'M5 21V4h9v17M14 9h5v12M8 8h3M8 12h3M8 16h3', video: 'M3 7h12v10H3zM15 11l6-3v8l-6-3', plug: 'M9 3v5M15 3v5M6 8h12v3a6 6 0 01-12 0V8zM12 17v4',
  chat: 'M4 5h16v11H9l-5 4V5z', pin: 'M12 21s7-6.2 7-11a7 7 0 10-14 0c0 4.8 7 11 7 11zM12 12a2 2 0 100-4 2 2 0 000 4z', badge: 'M12 3l2.5 5 5.5.8-4 3.9.9 5.5-4.9-2.6-4.9 2.6.9-5.5-4-3.9 5.5-.8z', crown: 'M3 8l4 4 5-7 5 7 4-4-2 11H5L3 8z', flag: 'M5 21V4h11l-2 4 2 4H5',
  shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z',
}
const Icon = ({ name }) => (
  <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={ICONS[name]} /></svg>
)

function Sidebar({ items, onNavigate }) {
  const { user } = useAuth()
  const { data: unread } = useApi('/chat/unread-count', undefined, { enabled: user.role !== 'platform_admin' })
  const chatUnread = unread?.count || 0
  return (
    <nav aria-label="Main" className="group flex h-full flex-col bg-slate-900 text-slate-300 [color-scheme:dark]">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white" aria-hidden>
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="3"><circle cx="12" cy="12" r="7" /></svg>
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold leading-tight text-white">WorkSphere</p>
          <p className="truncate text-xs text-slate-400">{user.company?.name}</p>
        </div>
      </div>
      <ul className="custom-scrollbar-dark flex-1 space-y-0.5 overflow-y-auto overflow-x-hidden px-3 pb-4">
        {items.map((n) => (
          <li key={n.to}>
            <NavLink to={n.to} end={n.end} onClick={onNavigate}
              className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${isActive ? 'bg-brand-600 text-white' : 'hover:bg-slate-800 hover:text-white'}`}>
              <Icon name={n.icon} />{n.label}
              {n.to === '/chat' && chatUnread > 0 && <span className="ml-auto rounded-full bg-brand-500 px-1.5 text-[11px] font-semibold text-white" aria-label={`${chatUnread} unread chat messages`}>{chatUnread}</span>}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}

export default function AppShell({ denied = false }) {
  const { user, logout, role } = useAuth()
  const [drawer, setDrawer] = useState(false)
  const [menu, setMenu] = useState(false)
  const { pathname } = useLocation()
  const crumbs = breadcrumbs(pathname)
  const items = navFor(role, user?.permissions)
  useEffect(() => { setDrawer(false); setMenu(false) }, [pathname])

  return (
    <div className="flex h-full">
      <a href="#main" className="sr-only z-[70] rounded bg-white px-3 py-2 focus:not-sr-only focus:fixed focus:left-2 focus:top-2">Skip to content</a>
      <aside className="hidden w-64 shrink-0 lg:block"><div className="fixed inset-y-0 w-64"><Sidebar items={items} /></div></aside>
      {drawer && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/50" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 left-0 w-64"><Sidebar items={items} onNavigate={() => setDrawer(false)} /></div>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-slate-200 bg-white/90 px-4 py-2.5 backdrop-blur sm:px-6">
          <button className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 lg:hidden" aria-label="Open navigation menu" onClick={() => setDrawer(true)}>
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" /></svg>
          </button>
          <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
            <ol className="flex items-center gap-1.5 truncate text-sm text-slate-500">
              {crumbs.map((c, i) => (
                <li key={i} className="flex items-center gap-1.5">
                  {i > 0 && <span aria-hidden>/</span>}
                  {c.to ? <Link to={c.to} className="hover:text-slate-900">{c.label}</Link> : <span aria-current="page" className="font-medium text-slate-900">{c.label}</span>}
                </li>
              ))}
            </ol>
          </nav>
          {role !== 'platform_admin' && <NotificationBell />}
          <div className="relative">
            <button onClick={() => setMenu(!menu)} aria-label={`${user.full_name}, ${ROLE_LABEL[role]} (account menu)`} aria-haspopup="true" aria-expanded={menu} className="flex items-center gap-2 rounded-full p-1 pr-2 hover:bg-slate-100">
              <Avatar name={user.full_name} userId={user.id} v={user.avatar_v} />
              <span className="hidden text-left sm:block">
                <span className="block text-sm font-medium leading-tight text-slate-900">{user.full_name}</span>
                <span className="block text-xs leading-tight text-slate-500">{ROLE_LABEL[role]}</span>
              </span>
            </button>
            {menu && (
              <div className="absolute right-0 mt-2 w-48 rounded-xl border border-slate-200 bg-white py-1 shadow-xl">
                <p className="truncate px-4 py-2 text-xs text-slate-500">{user.email}</p>
                {role !== 'platform_admin' && <Link to="/profile" className="block px-4 py-2 text-sm hover:bg-slate-50">My profile</Link>}
                <button onClick={logout} className="block w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-slate-50">Sign out</button>
              </div>
            )}
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
          {denied ? <AccessDenied path={pathname} /> : <Outlet />}
        </main>
        {role !== 'platform_admin' && <IncomingCall />}
      </div>
    </div>
  )
}
