import { Suspense, lazy } from 'react'
import { PageLoader, Tabs } from '../../components/ui'
import { usePersistentState } from '../../lib/usePersistentState'
import { useAuth } from '../auth/AuthContext'
import TodoPage from './TodoPage'

// The tasks assigned to you inside projects (managed by managers and team leaders) stay available on the second tab.
const ProjectTasks = lazy(() => import('../projects/MyTasksPage'))

export default function TasksHome() {
  const { role } = useAuth()
  const [tab, setTab] = usePersistentState('tasks-home-tab', 'todo', { store: 'session' })
  if (role === 'founder') return <TodoPage /> // founders have no project tasks of their own: just the personal list
  return (
    <>
      <Tabs tabs={[{ id: 'todo', label: 'My to-do list' }, { id: 'project', label: 'Project tasks' }]} value={tab} onChange={setTab} />
      {tab === 'project' ? <Suspense fallback={<PageLoader />}><ProjectTasks /></Suspense> : <TodoPage />}
    </>
  )
}
