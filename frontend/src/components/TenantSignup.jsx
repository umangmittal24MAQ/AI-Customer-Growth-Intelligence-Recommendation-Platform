import { useState } from 'react'
import { Loader2, Mail, LockKeyhole, Building2, ChevronDown, AlertTriangle, ArrowRight } from 'lucide-react'
import { signupTenant } from '../api/client'
import TrajectAuthLayout from './TrajectAuthLayout'

const DOMAINS = [
  { value: '', label: 'No preset — connect my data later' },
  { value: 'amazon', label: 'E-commerce · Amazon sample' },
  { value: 'traject-showcase', label: '⭐ Traject Showcase · 12 curated, labeled SaaS cases' },
  { value: 'techflow', label: 'SaaS · TechFlow sample' },
  { value: 'ironforge', label: 'Manufacturing · IronForge sample' },
  { value: 'brightmart', label: 'Retail · BrightMart sample' },
  { value: 'novasales', label: 'B2B Sales · NovaSales sample' },
]

export default function TenantSignup({ onSwitchToLogin }) {
  const [clientName, setClientName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [domain, setDomain] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  async function handleSubmit(e) {
    e.preventDefault()
    if(!clientName.trim() || !email.trim() || !password || !confirmPassword) { setError('Complete all fields to continue.'); return }
    if(password !== confirmPassword) { setError('Passwords do not match.'); return }
    setLoading(true); setError(''); setInfo('')
    try {
      await signupTenant(clientName.trim(), email.trim(), password, confirmPassword, domain)
      setPassword(''); setConfirmPassword('')
      setInfo('Workspace created. Use the sign-in link below to continue.')
    } catch(err) { setError(err.response?.data?.detail || 'Unable to create workspace. Check that the API is running.') }
    finally { setLoading(false) }
  }
  return <TrajectAuthLayout mode="signup">
    <h2 className="text-[29px] sm:text-[36px] font-extrabold tracking-[-.05em] leading-tight text-[#1c3024]">Build your intelligence<br/>workspace<span className="text-[#7bae42]">.</span></h2>
    <p className="mt-2 text-[#7a897e] text-[12px]">Create a tenant-isolated space to analyze your portfolio.</p>
    <form onSubmit={handleSubmit} className="space-y-4 mt-6">
      <div><label htmlFor="signup-company" className="traject-auth-label">Workspace / company name</label><div className="relative"><Building2 size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#8a9c8d]"/><input id="signup-company" required className="traject-auth-input" value={clientName} onChange={e=>setClientName(e.target.value)} placeholder="e.g. Northstar"/></div></div>
      <div><label htmlFor="signup-domain" className="traject-auth-label">Sample data <span className="font-normal">(optional)</span></label><div className="relative"><select id="signup-domain" className="traject-auth-input appearance-none !pl-3 pr-10" value={domain} onChange={e=>setDomain(e.target.value)}>{DOMAINS.map(d=><option key={d.value} value={d.value}>{d.label}</option>)}</select><ChevronDown size={16} className="absolute right-3.5 top-1/2 -translate-y-1/2 pointer-events-none text-[#8a9c8d]"/></div></div>
      <div><label htmlFor="signup-email" className="traject-auth-label">Work email</label><div className="relative"><Mail size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#8a9c8d]"/><input id="signup-email" type="email" autoComplete="email" required className="traject-auth-input" value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@company.com"/></div></div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3"><div><label htmlFor="signup-pass" className="traject-auth-label">Password</label><div className="relative"><LockKeyhole size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#8a9c8d]"/><input id="signup-pass" type="password" minLength={8} autoComplete="new-password" required className="traject-auth-input" value={password} onChange={e=>setPassword(e.target.value)} placeholder="8+ characters"/></div></div><div><label htmlFor="signup-confirm" className="traject-auth-label">Confirm password</label><div className="relative"><LockKeyhole size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#8a9c8d]"/><input id="signup-confirm" type="password" autoComplete="new-password" required className="traject-auth-input" value={confirmPassword} onChange={e=>setConfirmPassword(e.target.value)} placeholder="Repeat password"/></div></div></div>
      {error && <p role="alert" className="flex gap-2 text-red-700 bg-red-50 border border-red-200 rounded-xl text-[12px] p-3"><AlertTriangle size={16} className="shrink-0"/>{error}</p>}
      {info && <p role="status" className="text-[#2e643b] bg-[#e2f3d4] border border-[#b9df99] rounded-xl text-[12px] p-3">{info}</p>}
      <button disabled={loading || !!info} className="traject-auth-submit flex items-center justify-center gap-2" type="submit">{loading ? <><Loader2 size={16} className="animate-spin"/> Creating…</> : <>Create workspace <ArrowRight size={17}/></>}</button>
    </form>
    <div className="border-t border-[#dbe3d8] mt-7 pt-5 text-[12px] text-[#738578]">Already have a workspace? <button onClick={onSwitchToLogin} className="font-extrabold text-[#294c2c] hover:underline" type="button">Sign in →</button></div>
  </TrajectAuthLayout>
}
