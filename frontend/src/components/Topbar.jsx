import { useMemo, useState } from 'react'
import { Search, LogOut, ArrowUpRight, X } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { getTenantCredentials, clearTenantCredentials } from '../api/tenantSession'
import { useAppData } from '../context/AppDataContext'

export default function Topbar() {
  const { tenantId } = getTenantCredentials()
  const { customers } = useAppData()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [focused, setFocused] = useState(false)
  const matches = useMemo(() => query.trim().length > 0 ? customers.filter(c => (c.company_name || c.customer_name || '').toLowerCase().includes(query.toLowerCase())).slice(0, 6) : [], [customers, query])
  const handleSignOut = () => {
    clearTenantCredentials()
    window.dispatchEvent(new Event('traject:tenant-unauthorized'))
  }
  const go = (id) => { setQuery(''); setFocused(false); navigate(`/customers/${encodeURIComponent(id)}`) }
  return (
    <header className="traject-topbar sticky top-0 z-20 flex items-center justify-between px-4 sm:px-8 gap-3 h-[72px]">
      <div className="flex items-center gap-3 min-w-0 flex-1">
        <span className="hidden lg:inline text-[11px] font-extrabold uppercase tracking-[.16em] text-[#697873] mr-2">Intelligence / Workspace</span>
        <div className="relative w-full max-w-[370px]">
          <Search size={17} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#87948f] pointer-events-none"/>
          <input aria-label="Search accounts" value={query} onChange={e=>setQuery(e.target.value)} onFocus={()=>setFocused(true)} onBlur={()=>setTimeout(()=>setFocused(false), 160)} onKeyDown={e=>{ if(e.key === 'Enter' && matches.length) go(matches[0].customer_id); if(e.key === 'Escape'){ setQuery(''); setFocused(false) } }} placeholder="Search your accounts…" className="traject-search w-full rounded-xl py-2.5 pl-10 pr-10 text-[13px] outline-none"/>
          {query && <button type="button" aria-label="Clear search" className="absolute right-3 top-1/2 -translate-y-1/2 text-[#697873]" onClick={()=>setQuery('')}><X size={15}/></button>}
          {focused && query.trim() && <div className="absolute top-full mt-2 left-0 right-0 bg-white shadow-xl rounded-2xl border border-[#e2e9e1] py-2 z-50 max-h-[260px] overflow-auto">
            {matches.length ? matches.map(c=><button type="button" key={c.customer_id} onMouseDown={e=>e.preventDefault()} onClick={()=>go(c.customer_id)} className="w-full flex justify-between items-center text-left px-4 py-2.5 hover:bg-[#eff5e9] text-[13px] text-[#26322d]"><span className="truncate">{c.company_name || c.customer_name}</span><ArrowUpRight size={14}/></button>) : <p className="px-4 py-3 text-[12px] text-[#76837d]">No matching accounts</p>}
          </div>}
        </div>
      </div>
      <div className="flex items-center gap-2 sm:gap-4 shrink-0">
        <Link to="/chat" className="hidden sm:inline-flex items-center gap-1.5 text-[12px] font-bold text-[#42574a] hover:text-[#1c3023]">Ask Traject <ArrowUpRight size={14}/></Link>
        <div className="hidden lg:block h-6 w-px bg-[#e1e7df]"/>
        <div className="flex items-center gap-2" title={tenantId || 'Workspace'}><span className="traject-avatar">{(tenantId || 'T').slice(0,1).toUpperCase()}</span><span className="hidden xl:block text-[12px] font-bold truncate max-w-[130px] text-[#25332b]">{tenantId || 'Workspace'}</span></div>
        <button aria-label="Sign out" title="Sign out" onClick={handleSignOut} className="traject-signout p-2.5 rounded-xl hover:bg-[#eaf0e6] text-[#64736b]"><LogOut size={17}/></button>
      </div>
    </header>
  )
}
