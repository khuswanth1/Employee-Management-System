export default function AuthLayout({ subtitle, children }) {
  return (
    <main className="flex min-h-full items-center justify-center bg-gradient-to-br from-brand-50 via-white to-slate-100 px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-600 text-white shadow-lg" aria-hidden>
            <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="12" cy="12" r="7" /><path d="M12 5v14M5 12h14" strokeLinecap="round" /></svg>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">WorkSphere</h1>
          <p className="mt-1 text-sm text-slate-500">{subtitle}</p>
        </div>
        {children}
      </div>
    </main>
  )
}
