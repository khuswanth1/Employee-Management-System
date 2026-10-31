# WorkSphere — Frontend Application

A responsive, high-performance Single Page Application (SPA) for the **WorkSphere** Multi-Tenant Employee & Project Management platform. Built with **React 19**, **Vite**, **Tailwind CSS v4**, and **TanStack Query**.

---

## Tech Stack

- **Framework**: [React 19](https://react.dev/)
- **Build Tool**: [Vite 8](https://vitejs.dev/) with Fast Refresh & ESM
- **Styling**: [Tailwind CSS v4](https://tailwindcss.com/)
- **Routing**: [React Router 7](https://reactrouter.com/)
- **Server State & Caching**: [TanStack Query v5](https://tanstack.com/query/latest)
- **Data Visualization**: [Recharts v3](https://recharts.org/)
- **Real-Time & Media**: Native WebSockets and WebRTC for chat and calls
- **Testing**: [Vitest](https://vitest.dev/) + [React Testing Library](https://testing-library.com/docs/react-testing-library/intro/) + [jsdom](https://github.com/jsdom/jsdom)

---

## Project Structure

```text
frontend/
├── src/
│   ├── components/         # Shared reusable UI primitives (Buttons, Modals, Inputs, etc.)
│   ├── features/           # Domain-driven feature modules
│   │   ├── admin/          # Tenant administration & audit settings
│   │   ├── attendance/     # Clock-in / clock-out, timesheets, shift scheduling
│   │   ├── auth/           # Login, MFA verification, password recovery, session management
│   │   ├── chat/           # WebSocket real-time messaging, audio messages, reactions
│   │   ├── dashboard/      # Tenant analytics, company metrics, summary widgets
│   │   ├── employees/      # Employee directory, org chart, lifecycle transitions, profiles
│   │   ├── escalations/    # Ticket & issue escalation tracking
│   │   ├── layout/         # AppShell, navigation bar, access control screens
│   │   ├── leave/          # Leave requests, approval queues, holiday calendar
│   │   ├── meetings/       # WebRTC video/audio meetings, incoming call alerts
│   │   ├── notifications/  # Notification center bell, live toast alerts
│   │   ├── org/            # Departments, branches, board analytics, management hierarchy
│   │   ├── payroll/        # Salary runs, payslip viewer & generation
│   │   ├── performance/    # Goals, performance reviews, feedback cycles
│   │   ├── platform/       # Multi-tenant management & platform administration
│   │   ├── projects/       # Projects, milestones, task Kanban/list, comments
│   │   ├── teams/          # Team rosters, performance metrics, team details
│   │   ├── todos/          # Nested personal & team task checklists
│   │   ├── updates/        # Daily asynchronous standup updates
│   │   └── webhooks/       # Outbound webhook registrations & status monitoring
│   ├── lib/                # API client, storage helpers, navigation utils, custom hooks
│   ├── index.css           # Global stylesheet & Tailwind CSS entrypoint
│   ├── main.jsx            # Application root mounting & providers
│   └── test-setup.js       # Vitest setup & Jest-DOM assertions
├── Dockerfile              # Multi-stage Docker build for production
├── index.html              # HTML entrypoint
├── nginx.spa.conf          # Nginx routing configuration for client-side routing
├── package.json            # Dependencies and npm scripts
└── vite.config.js          # Vite config, dev API proxy, and Vitest setup
```

---

## Getting Started

### Prerequisites

- **Node.js**: v18.0.0 or higher
- **npm**: v9.0.0 or higher
- Running WorkSphere **backend** API (defaults to `http://localhost:8000`)

### Installation

1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

### Environment Configuration

The Vite dev server proxies API calls and WebSockets to the backend automatically. To change the backend proxy destination, configure `VITE_API_PROXY`:

```bash
# Optional: defaults to http://localhost:8000
VITE_API_PROXY=http://localhost:8000
```

> **Note**: Frontend environment files should never contain secrets or credentials.

---

## Available Scripts

| Command | Description |
|---|---|
| `npm run dev` | Starts the Vite dev server with Hot Module Replacement on `http://localhost:5173` |
| `npm run build` | Compiles and bundles production-ready assets into the `dist/` directory |
| `npm run preview` | Locally serves the production build from `dist/` for verification |
| `npm test` | Executes the Vitest automated test suite |

---

## API Proxy & Real-Time Setup

The development server includes a built-in reverse proxy in `vite.config.js`:
- All requests starting with `/api` are routed to the backend server (default: `http://localhost:8000`).
- Supports full WebSocket forwarding (`ws: true`) for chat channels and WebRTC meeting signaling without CORS configuration.

---

## Docker & Production Deployment

For production, the frontend is built into static HTML/JS/CSS assets and served via Nginx with single-page application fallback routing:

```bash
# Build the production Docker image
docker build -t worksphere-frontend:latest .

# Run containerized on port 80
docker run -p 80:80 worksphere-frontend:latest
```

