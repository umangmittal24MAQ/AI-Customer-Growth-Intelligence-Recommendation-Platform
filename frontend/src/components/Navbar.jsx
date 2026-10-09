import { Link, useLocation } from 'react-router-dom'

const links = [
  { to: '/', label: 'Dashboard' },
  { to: '/customers', label: 'Customers' },
  { to: '/tracking', label: 'Tracking' },
]

export default function Navbar() {
  const { pathname } = useLocation()
  return (
    <nav className="bg-white border-b border-slate-200 sticky top-0 z-10">
      <div className="max-w-7xl mx-auto px-6 flex items-center justify-between h-16">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg bg-indigo-600 text-white grid place-items-center font-bold">
            U
          </div>
          <span className="font-semibold text-slate-900">
            Traject
          </span>
        </div>
        <div className="flex gap-1">
          {links.map((l) => {
            const active =
              l.to === '/' ? pathname === '/' : pathname.startsWith(l.to)
            return (
              <Link
                key={l.to}
                to={l.to}
                className={`px-3 py-2 rounded-md text-sm font-medium transition ${
                  active
                    ? 'bg-indigo-50 text-indigo-700'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {l.label}
              </Link>
            )
          })}
        </div>
      </div>
    </nav>
  )
}
