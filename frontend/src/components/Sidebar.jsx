import { NavLink, Link } from 'react-router-dom'
import { LayoutGrid, UsersRound, MessagesSquare, SlidersHorizontal, ArrowUpRight, ShieldCheck, GitBranch } from 'lucide-react'
import BrandMark from './BrandMark'

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutGrid, end: true },
  { to: '/customers', label: 'Accounts', icon: UsersRound },
  { to: '/chat', label: 'AI workbench', icon: MessagesSquare },
  { to: '/settings', label: 'Workspace settings', icon: SlidersHorizontal },
]

export default function Sidebar() {
  return (
    <>
      <aside className="traject-sidebar hidden md:flex fixed inset-y-0 left-0 z-30 w-[244px] flex-col">
        <Link to="/" className="flex items-center gap-3 px-6 h-[86px]" aria-label="Traject overview">
          <BrandMark size={38} />
          <span className="flex flex-col leading-none">
            <span className="text-[24px] tracking-[-.07em] font-extrabold text-white">traject<span className="text-[#bdf583]">.</span></span>
            <span className="text-[9px] uppercase tracking-[.25em] text-[#93a4a0] mt-[7px] font-bold">Revenue intelligence</span>
          </span>
        </Link>
        <div className="px-5 pt-8">
          <div className="px-3 text-[10px] tracking-[.18em] uppercase font-extrabold text-[#839893] mb-4">Workspace</div>
          <nav className="space-y-1.5" aria-label="Main navigation">
            {NAV.map(({to, label, icon: Icon, end}) => (
              <NavLink key={to} to={to} end={end} className={({isActive}) => `traject-nav-item ${isActive ? 'is-active' : ''}`}>
                <Icon size={18} strokeWidth={1.9}/><span>{label}</span><ArrowUpRight size={13} className="ml-auto nav-arrow"/>
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="mt-auto p-4">
          <Link to="/chat" className="traject-sidebar-feature group">
            <span className="inline-flex items-center gap-2 text-[#bdf583] text-[10px] font-bold tracking-[.14em] uppercase"><GitBranch size={14}/> Decision engine</span>
            <span className="block mt-2 text-white font-bold text-[16px] leading-snug">Move from signals<br/>to action.</span>
            <span className="flex justify-between items-center text-[11px] mt-4 text-[#bfcac6]">Open your workbench <ArrowUpRight size={16} className="group-hover:-translate-y-0.5 group-hover:translate-x-0.5 transition-transform"/></span>
          </Link>
          <div className="flex items-center gap-2 text-[#80948e] text-[11px] px-3 mt-5"><ShieldCheck size={14}/> Tenant-scoped workspace</div>
        </div>
      </aside>
      <nav aria-label="Mobile navigation" className="traject-mobile-nav md:hidden fixed bottom-0 left-0 right-0 z-40 flex justify-around px-2 py-2">
        {NAV.map(({to, label, icon: Icon, end}) => <NavLink key={to} to={to} end={end} className={({isActive})=>`mobile-nav-item ${isActive ? 'is-active' : ''}`}><Icon size={19}/><span>{label === 'Workspace settings' ? 'Settings' : label === 'AI workbench' ? 'AI' : label}</span></NavLink>)}
      </nav>
    </>
  )
}
