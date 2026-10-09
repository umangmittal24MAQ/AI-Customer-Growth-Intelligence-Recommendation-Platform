import { useState } from 'react'
import { Loader2, Mail, LockKeyhole, ArrowRight, AlertTriangle } from 'lucide-react'
import { loginTenant } from '../api/client'
import { setTenantCredentials } from '../api/tenantSession'
import TrajectAuthLayout from './TrajectAuthLayout'

export default function TenantLogin({ onSignedIn, onSwitchToSignup }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  async function handleSubmit(e) {
    e.preventDefault()
    if (!email.trim() || !password) { setError('Email and password are required.'); return }
    setLoading(true); setError(''); setInfo('')
    try {
      const result = await loginTenant(email.trim(), password)
      setTenantCredentials(result.tenant_id, result.api_key)
      if(result.warning) setInfo(result.warning)
      onSignedIn()
    } catch (err) { setError(err.response?.data?.detail || 'Unable to sign in. Check that the API is running.') }
    finally { setLoading(false) }
  }
  return <TrajectAuthLayout mode="login">
    <h2 className="text-[32px] sm:text-[39px] tracking-[-.05em] leading-tight font-extrabold text-[#1c3024]">Your next move<br/>starts here<span className="text-[#7bae42]">.</span></h2>
    <p className="mt-3 text-[13px] text-[#7a897e]">Sign in to uncover what matters across your accounts.</p>
    <form onSubmit={handleSubmit} className="mt-9 space-y-5">
      <div><label className="traject-auth-label" htmlFor="login-email">Work email</label><div className="relative"><Mail size={17} className="absolute top-1/2 -translate-y-1/2 left-3.5 text-[#8a9c8d]"/><input id="login-email" autoComplete="email" required type="email" className="traject-auth-input" value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@company.com"/></div></div>
      <div><label className="traject-auth-label" htmlFor="login-pass">Password</label><div className="relative"><LockKeyhole size={17} className="absolute top-1/2 -translate-y-1/2 left-3.5 text-[#8a9c8d]"/><input id="login-pass" autoComplete="current-password" required type="password" className="traject-auth-input" value={password} onChange={e=>setPassword(e.target.value)} placeholder="Enter your password"/></div></div>
      {error && <div role="alert" className="flex items-start gap-2 bg-red-50 text-red-700 border border-red-200 p-3 rounded-xl text-[12px]"><AlertTriangle size={15} className="shrink-0"/>{error}</div>}
      {info && <div role="status" className="bg-lime-50 text-green-900 border border-green-200 p-3 rounded-xl text-[12px]">{info}</div>}
      <button disabled={loading} type="submit" className="traject-auth-submit flex justify-center items-center gap-2">{loading ? <><Loader2 size={16} className="animate-spin"/> Signing in…</> : <>Enter workspace <ArrowRight size={17}/></>}</button>
    </form>
    <div className="border-t border-[#dbe3d8] mt-8 pt-6 text-[12px] text-[#738578]">New to Traject? <button type="button" className="font-extrabold text-[#294c2c] hover:underline" onClick={onSwitchToSignup}>Create an account →</button></div>
  </TrajectAuthLayout>
}
