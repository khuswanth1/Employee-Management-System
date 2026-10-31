import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { PageLoader } from './components/ui'
import { useAuth } from './features/auth/AuthContext'
import LoginPage from './features/auth/LoginPage'
import { ForgotPasswordPage, ResetPasswordPage, VerifyEmailPage } from './features/auth/RecoveryPages'
import AppShell from './features/layout/AppShell'
import { canAccess } from './lib/nav'

const page = (loader) => lazy(loader)
const Dashboard = page(() => import('./features/dashboard/DashboardPage'))
const MyTasks = page(() => import('./features/todos/TasksHome'))
const Projects = page(() => import('./features/projects/ProjectsPage'))
const ProjectDetail = page(() => import('./features/projects/ProjectDetailPage'))
const Teams = page(() => import('./features/teams/TeamsPage'))
const TeamAnalytics = page(() => import('./features/teams/TeamAnalyticsPage'))
const TeamDetail = page(() => import('./features/teams/TeamDetailPage'))
const Updates = page(() => import('./features/updates/MyUpdatesPage'))
const TeamUpdates = page(() => import('./features/updates/TeamUpdatesPage'))
const Attendance = page(() => import('./features/attendance/AttendancePage'))
const AttendanceTeam = page(() => import('./features/attendance/AttendanceReportPage'))
const AttendanceCorrections = page(() => import('./features/attendance/CorrectionsQueuePage'))
const AttendanceSetup = page(() => import('./features/attendance/AttendanceSetupPage'))
const Leave = page(() => import('./features/leave/LeavePage'))
const LeaveApprovals = page(() => import('./features/leave/LeaveApprovalsPage'))
const LeaveBalances = page(() => import('./features/leave/LeaveBalancesPage'))
const Employees = page(() => import('./features/employees/EmployeesPage'))
const EmployeeDetail = page(() => import('./features/employees/ColleagueCard'))
const OrgChart = page(() => import('./features/employees/OrgChartPage'))
const Lifecycle = page(() => import('./features/employees/LifecyclePage'))
const Departments = page(() => import('./features/employees/DepartmentsPage'))
const Branches = page(() => import('./features/org/BranchesPage'))
const Managers = page(() => import('./features/org/ManagersPage'))
const BoardMembers = page(() => import('./features/org/BoardMembersPage'))
const BoardAnalytics = page(() => import('./features/org/BoardAnalyticsPage'))
const Escalations = page(() => import('./features/escalations/EscalationsPage'))
const Holidays = page(() => import('./features/leave/HolidaysPage'))
const Chat = page(() => import('./features/chat/ChatPage'))
const Meetings = page(() => import('./features/meetings/MeetingsPage'))
const MeetingRoom = page(() => import('./features/meetings/MeetingRoomPage'))
const Webhooks = page(() => import('./features/webhooks/WebhooksPage'))
const Admin = page(() => import('./features/admin/AdminPage'))
const Performance = page(() => import('./features/performance/PerformancePage'))
const Payroll = page(() => import('./features/payroll/PayrollPage'))
const PayrollRun = page(() => import('./features/payroll/PayrollRunPage'))
const MyPayslips = page(() => import('./features/payroll/MyPayslipsPage'))
const Notifications = page(() => import('./features/notifications/NotificationsPage'))
const Profile = page(() => import('./features/auth/ProfilePage'))
const Companies = page(() => import('./features/platform/CompaniesPage'))

function Protected({ children }) {
  const { user, loading, role } = useAuth()
  const location = useLocation()
  if (loading) return <PageLoader />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (role === 'platform_admin' && !location.pathname.startsWith('/platform')) return <Navigate to="/platform" replace />
  if (role === 'board_member' && location.pathname === '/') return <Navigate to="/board" replace />
  if (!canAccess(role, location.pathname, user.id, user.permissions)) return <AppShell denied />
  return children
}

export default function App() {
  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />
        <Route element={<Protected><AppShell /></Protected>}>
          <Route index element={<Dashboard />} />
          <Route path="my-tasks" element={<MyTasks />} />
          <Route path="projects" element={<Projects />} />
          <Route path="projects/:id" element={<ProjectDetail />} />
          <Route path="teams" element={<Teams />} />
          <Route path="teams/analytics" element={<TeamAnalytics />} />
          <Route path="teams/:id" element={<TeamDetail />} />
          <Route path="updates" element={<Updates />} />
          <Route path="updates/team" element={<TeamUpdates />} />
          <Route path="attendance" element={<Attendance />} />
          <Route path="attendance/team" element={<AttendanceTeam />} />
          <Route path="attendance/corrections" element={<AttendanceCorrections />} />
          <Route path="attendance/setup" element={<AttendanceSetup />} />
          <Route path="leave" element={<Leave />} />
          <Route path="leave/approvals" element={<LeaveApprovals />} />
          <Route path="leave/balances" element={<LeaveBalances />} />
          <Route path="employees" element={<Employees />} />
          <Route path="employees/:id" element={<EmployeeDetail />} />
          <Route path="org-chart" element={<OrgChart />} />
          <Route path="lifecycle" element={<Lifecycle />} />
          <Route path="departments" element={<Departments />} />
          <Route path="chat" element={<Chat />} />
          <Route path="holidays" element={<Holidays />} />
          <Route path="performance" element={<Performance />} />
          <Route path="payroll" element={<Payroll />} />
          <Route path="payroll/runs/:id" element={<PayrollRun />} />
          <Route path="payslips" element={<MyPayslips />} />
          <Route path="branches" element={<Branches />} />
          <Route path="managers" element={<Managers />} />
          <Route path="board-members" element={<BoardMembers />} />
          <Route path="board" element={<BoardAnalytics />} />
          <Route path="escalations" element={<Escalations />} />
          <Route path="meetings" element={<Meetings />} />
          <Route path="meetings/:room" element={<MeetingRoom />} />
          <Route path="webhooks" element={<Webhooks />} />
          <Route path="admin" element={<Admin />} />
          <Route path="notifications" element={<Notifications />} />
          <Route path="profile" element={<Profile />} />
          <Route path="platform" element={<Companies />} />
          <Route path="tasks/:id" element={<Navigate to="/my-tasks" replace />} />
          <Route path="*" element={<div className="py-20 text-center text-slate-500">Page not found</div>} />
        </Route>
      </Routes>
    </Suspense>
  )
}
