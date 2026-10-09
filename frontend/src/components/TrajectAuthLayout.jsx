import { Activity, ArrowUpRight, CheckCircle2, CircleDot, Radar } from 'lucide-react'
import BrandMark from './BrandMark'

export default function TrajectAuthLayout({ mode, children }) {
  return <div className="traject-auth-shell">
    <aside className="traject-auth-story text-white">
      <div className="relative z-10 flex items-center gap-3">
        <BrandMark size={44}/>
        <div className="leading-tight"><div className="text-[29px] font-extrabold tracking-[-.075em]">traject<span className="text-[#bdf583]">.</span></div><div className="text-[9px] text-[#93aa9c] font-extrabold uppercase tracking-[.2em]">Revenue intelligence</div></div>
      </div>
      <div className="auth-story-details relative z-10 mt-auto mb-auto pt-24">
        <div className="inline-flex items-center gap-2 rounded-full bg-[#bdf5831c] border border-[#bdf58338] text-[#d8ffb8] py-2 px-3 text-[10px] font-extrabold uppercase tracking-[.15em]"><Radar size={14}/> Decision intelligence platform</div>
        <h1 className="text-[44px] xl:text-[55px] tracking-[-.055em] font-extrabold leading-[1.1] mt-6">Follow the signal.<br/><span className="text-[#bdf583]">Find the growth.</span></h1>
        <p className="max-w-[415px] text-[#b2c6b7] text-[14px] leading-relaxed mt-5">All your customer context in one place. Better decisions for expansion, retention and the next conversation.</p>
        <div className="traject-auth-signal mt-14">
          <p className="text-[10px] text-[#a6bea9] font-extrabold uppercase tracking-[.17em] mb-4">How Traject thinks</p>
          <div className="flex items-center justify-between gap-1 text-[12px] font-bold"><span className="inline-flex items-center gap-2"><CircleDot size={15} className="text-[#bdf583]"/> Signals</span><ArrowUpRight size={16} className="text-[#93b39b]"/><span className="inline-flex items-center gap-2"><Activity size={15} className="text-[#bdf583]"/> Insight</span><ArrowUpRight size={16} className="text-[#93b39b]"/><span className="inline-flex items-center gap-2"><CheckCircle2 size={15} className="text-[#bdf583]"/> Action</span></div>
        </div>
      </div>
      <p className="auth-story-details relative z-10 text-[#8ea997] text-[11px]">Traject · Built for thoughtful account teams</p>
    </aside>
    <main className="traject-auth-formside">
      <div className="traject-auth-form">
        <p className="text-[10px] tracking-[.2em] uppercase text-[#718273] font-extrabold mb-4">{mode === 'signup' ? 'Create a workspace' : 'Welcome to Traject'}</p>
        {children}
      </div>
    </main>
  </div>
}
