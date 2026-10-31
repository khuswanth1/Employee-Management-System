import { useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import TaskModal from './TaskModal'

/** Loads what TaskModal needs for one project, so any page can create/edit/delete a task. */
export default function TaskEditor({ open, onClose, projectId, task }) {
  const { user } = useAuth()
  const enabled = open && !!projectId
  const { data: project } = useApi(projectId ? `/projects/${projectId}` : null, null, { enabled })
  const { data: taskData } = useApi(projectId ? `/projects/${projectId}/tasks` : null, null, { enabled })
  const { data: dir } = useApi('/employees/directory', null, { enabled })
  const everyone = dir?.items || []

  if (!open || !project) return null
  const isOwner = Boolean(project.can_edit)
  const canManage = isOwner || Boolean(project.can_assign_tasks)
  // team leaders can only hand work to the members of their own team
  const people = project.assignable_ids ? everyone.filter((p) => project.assignable_ids.includes(p.id)) : everyone

  return (
    <TaskModal
      open
      onClose={onClose}
      project={project}
      task={task}
      tasks={taskData?.items || []}
      milestones={project.milestones || []}
      people={people}
      canManage={canManage}
      isOwner={isOwner}
      meId={user.id}
    />
  )
}
