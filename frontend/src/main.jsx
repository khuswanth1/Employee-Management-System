import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { ToastProvider } from './components/ui'
import { AuthProvider } from './features/auth/AuthContext'
import { NotificationsProvider } from './features/notifications/NotificationsProvider'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: (n, e) => e?.status >= 500 && n < 2, refetchOnWindowFocus: false, staleTime: 15_000 },
    // Saves must fail at once when offline (the form keeps its input and says so) instead of waiting silently and firing on reconnect.
    mutations: { networkMode: 'always' },
  },
})

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <AuthProvider>
            <NotificationsProvider>
              <App />
            </NotificationsProvider>
          </AuthProvider>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
)
