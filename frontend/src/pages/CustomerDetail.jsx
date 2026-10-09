import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft, Play, Loader2, AlertTriangle, Brain, X, Sparkles,
  ChevronRight, AlertOctagon, ThumbsUp, ThumbsDown, CheckCircle2,
  CalendarClock, Gift, GraduationCap, ClipboardCheck, PhoneCall, Eye,
  Mail, Calendar, TrendingUp, Award, BarChart2, Package, ChevronDown
} from 'lucide-react'
import { getCustomerAnalysis, generateRecommendations, submitFeedback, triggerPowerAutomateEmail } from '../api/client'
import InsightCard from '../components/InsightCard'
import MeetingScheduler from '../components/MeetingScheduler'

const RETENTION_ACTION_META = {
  executive_meeting: { icon: CalendarClock, label: 'Schedule meeting', className: 'bg-indigo-50 text-indigo-700 ring-indigo-500/20' },
  complimentary_offer: { icon: Gift, label: 'Complimentary offer', className: 'bg-pink-50 text-pink-700 ring-pink-500/20' },
  training_session: { icon: GraduationCap, label: 'Offer training', className: 'bg-sky-50 text-sky-700 ring-sky-500/20' },
  account_review: { icon: ClipboardCheck, label: 'Account review', className: 'bg-gray-100 text-gray-700 ring-gray-500/20' },
  proactive_outreach: { icon: PhoneCall, label: 'Check in', className: 'bg-teal-50 text-teal-700 ring-teal-500/20' },
  monitor: { icon: Eye, label: 'Monitor', className: 'bg-gray-100 text-gray-500 ring-gray-500/20' },
}

const CHURN_BADGE = {
  HIGH: 'bg-red-100 text-red-700 ring-red-500/20',
  MEDIUM: 'bg-amber-100 text-amber-700 ring-amber-500/20',
  LOW: 'bg-emerald-100 text-emerald-700 ring-emerald-500/20',
}

function Card({ children, className = '' }) {
  return <div className={`bg-white rounded-2xl border border-gray-200/60 shadow-card overflow-hidden ${className}`}>{children}</div>
}

// Splits a prose rationale into clean bullet points.
// Handles sentences ending with . ! ? as well as lines that start with - or numbers.
function toBullets(text) {
  if (!text) return []
  // Strip low-confidence prefix boilerplate (pipeline fallback wrapper)
  const clean = text
    .replace(/^Suggested (upsell|cross-sell|upgrade):[^(]+\(Low-confidence starting point \(/i, '')
    .replace(/^Low-confidence starting point[^)]+\)/i, '')
    .replace(/\)\s*$/, '')
    .trim()
  // Split on sentence boundaries
  return clean
    .split(/(?<=[.!?])\s+(?=[A-Z(])/)
    .map(s => s.trim())
    .filter(s => s.length > 10)
}

function BulletList({ text, className = '' }) {
  const items = toBullets(text)
  if (!items.length) return null
  return (
    <ul className={`list-disc pl-4 space-y-1 ${className}`}>
      {items.map((item, i) => <li key={i}>{item}</li>)}
    </ul>
  )
}

function Section({ icon: Icon, title, children, iconColor = 'text-blue-600', right }) {
  return (
    <Card>
      <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon size={16} className={iconColor} />
          <h3 className="text-[14px] font-bold text-gray-900">{title}</h3>
        </div>
        {right}
      </div>
      <div className="p-5">{children}</div>
    </Card>
  )
}

// Audit summary: decisions and source excerpts, not private chain-of-thought.
function TraceModal({ open, onClose, trace, title, content }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-900/40 backdrop-blur-sm" onClick={onClose}>
      <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
        onClick={e => e.stopPropagation()}
        className="bg-white rounded-2xl shadow-xl w-full max-w-2xl overflow-hidden max-h-[85vh] flex flex-col">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
          <div className="flex items-center gap-2"><Brain size={18} className="text-violet-600" /><h3 className="text-[15px] font-bold text-gray-900">How we got here</h3></div>
          <button onClick={onClose} className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"><X size={16} /></button>
        </div>
        <div className="p-6 overflow-y-auto">
          {content && (
            <div className="mb-6">
              {title && <h4 className="text-[14px] font-bold text-gray-900 mb-2">{title}</h4>}
              <div className="bg-gray-50 p-4 rounded-xl border border-gray-100">
                <BulletList text={content} className="text-[13px] text-gray-600 leading-relaxed" />
              </div>
            </div>
          )}
          {trace?.length ? (
            <div className="space-y-0">
              <h4 className="text-[11px] font-bold text-gray-400 uppercase tracking-widest mb-4">Agent pipeline</h4>
              {trace.map((step, i) => (
                <div key={i} className="flex gap-3 pb-6 last:pb-0">
                  <div className="flex flex-col items-center">
                    <div className="h-7 w-7 rounded-full bg-violet-600 text-white text-[11px] font-bold grid place-items-center shrink-0 z-10">{i + 1}</div>
                    {i < trace.length - 1 && <div className="flex-1 w-px bg-violet-200 mt-2" />}
                  </div>
                  <div className="flex-1 mt-0.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-[13px] text-gray-800">{step.agent}</span>
                      {step.mode && <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full uppercase ${step.mode === 'llm' ? 'bg-violet-100 text-violet-700' : 'bg-gray-100 text-gray-500'}`}>{step.mode === 'llm' ? 'LLM' : 'Rules'}</span>}
                    </div>
                    <BulletList text={step.detail} className="text-[12px] text-gray-600 mt-1 leading-relaxed" />
                    {step.basis && (
                      <div className="mt-2 rounded-xl bg-violet-50/50 border border-violet-100/50 px-4 py-3">
                        <p className="text-[10px] font-bold text-violet-600 uppercase tracking-wider mb-1">Reasoning</p>
                        <BulletList text={step.basis} className="text-[12px] text-gray-700" />
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-center py-6 text-[12px] text-gray-400">Run "Analyze" to see the full agent trace.</p>
          )}
        </div>
      </motion.div>
    </div>
  )
}

export default function CustomerDetail() {
  const { id } = useParams()
  const [a, setA] = useState(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState(null)
  const [trace, setTrace] = useState(null)
  const [modal, setModal] = useState({ open: false, title: '', content: '' })
  const [feedback, setFeedback] = useState(null)
  
  const [emailLoading, setEmailLoading] = useState(false)
  const [emailSent, setEmailSent] = useState(false)
  const [showMeetingScheduler, setShowMeetingScheduler] = useState(false)

  const load = () => { setLoading(true); getCustomerAnalysis(id).then(setA).catch(() => setA(null)).finally(() => setLoading(false)) }
  useEffect(load, [id])

  const run = async () => {
    setRunning(true); setTrace(null); setRunError(null)
    try { const r = await generateRecommendations(id); setTrace(r.trace); load() }
    catch (e) { setRunError(e?.response?.data?.detail || 'Analysis failed to run.') }
    finally { setRunning(false) }
  }

  const openModal = (title, content) => setModal({ open: true, title, content })

  const sendFeedback = async (status) => {
    const rec = a?.all_recommendations?.[0]
    if (!rec?.id) return
    setFeedback(status)
    try { await submitFeedback(rec.id, status) } catch { setFeedback(null) }
  }

  const triggerEmail = async () => {
    setEmailLoading(true);
    try {
      await triggerPowerAutomateEmail(id);
      setEmailSent(true);
      setTimeout(() => setEmailSent(false), 3000);
    } catch(e) {
      alert("Failed to trigger Power Automate: " + (e.response?.data?.detail || e.message));
    } finally {
      setEmailLoading(false);
    }
  }

  if (loading) return (
    <div className="space-y-4 animate-pulse">
      <div className="h-6 w-32 skeleton" /><div className="h-10 w-64 skeleton" /><div className="h-32 skeleton" />
      <div className="grid grid-cols-2 gap-4">{[...Array(2)].map((_, i) => <div key={i} className="h-28 skeleton" />)}</div>
    </div>
  )
  if (!a) return (
    <div className="text-center py-20">
      <AlertTriangle size={40} className="text-gray-300 mx-auto" />
      <p className="mt-3 text-[14px] font-semibold text-gray-500">Customer not found</p>
      <Link to="/customers" className="inline-flex items-center gap-1 mt-4 text-[13px] font-semibold text-blue-600 hover:text-blue-700">Back to customers <ChevronRight size={14} /></Link>
    </div>
  )

  const cs = a.customer_summary || {}
  const current = cs.current_product || cs.plan_tier || '—'

  // ---- Not analyzed yet ----
  if (a.analyzed === false) {
    const canRun = a.can_run_analysis !== false
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-5">
        <Link to="/customers" className="inline-flex items-center gap-1 text-[12px] font-semibold text-gray-500 hover:text-blue-600 transition-colors"><ArrowLeft size={14} /> Back to customers</Link>
        {a.decision_status && a.decision_status !== 'qualified' && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3" role="status">
          <div className="flex items-center gap-2 text-amber-900 text-[13px] font-bold">
            <AlertTriangle size={16} /> No approved upsell — {a.decision_status.replaceAll('_', ' ')}
          </div>
          <p className="mt-1 text-[12px] text-amber-800">Traject did not find a verified recommendation for this account. Review the source evidence or improve the customer data before pitching a product.</p>
        </div>
      )}
      {!!a.evidence?.length && (
        <Section icon={ClipboardCheck} title="Evidence trail · imported data" iconColor="text-emerald-700">
          <p className="text-[12px] text-gray-500 mb-3">Source fields shown below are copied from this account's input data; they are not generated sales claims.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {a.evidence.slice(0, 8).map((e, i) => (
              <div key={i} className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">
                <div className="text-[10px] uppercase tracking-wide text-gray-500">{e.source} · {e.field}</div>
                <div className="text-[12px] font-medium text-gray-800 break-all">{String(e.value)}</div>
              </div>
            ))}
          </div>
        </Section>
      )}
      {a.data_gaps?.length > 0 && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3">
            <div className="flex items-center gap-2 mb-1.5"><AlertOctagon size={15} className="text-red-500" /><p className="text-[12.5px] font-bold text-red-800">Missing data</p></div>
            <ul className="space-y-1">{a.data_gaps.map((g, i) => <li key={i} className="text-[12px] text-red-700">• {g}</li>)}</ul>
          </div>
        )}
        <div className="bg-white rounded-2xl border border-gray-200/60 shadow-card py-16 px-6 text-center">
          <Brain size={36} className="text-gray-300 mx-auto" />
          <h1 className="mt-4 text-[18px] font-bold text-gray-900">{cs.company_name}</h1>
          <p className="mt-1.5 text-[13px] text-gray-500 max-w-md mx-auto">Currently on <span className="font-semibold text-gray-700">{current}</span>. Run the analysis to see what we can upsell them and how confident we are.</p>
          {!canRun && <p className="mt-3 text-[12px] font-semibold text-red-600">Upload a product catalog before running analysis.</p>}
          {runError && <p className="mt-3 text-[12px] font-semibold text-red-600">{runError}</p>}
          <button onClick={run} disabled={running || !canRun}
            className="mt-5 inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 text-white text-[13px] font-semibold shadow-sm shadow-blue-500/20 hover:bg-blue-700 disabled:opacity-50 transition-all mx-auto">
            {running ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}{running ? 'Running…' : 'Analyze Customer'}
          </button>
        </div>
        {a.insights?.length > 0 && (
          <Section icon={Sparkles} title="Preliminary signals">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {a.insights.map(ins => <InsightCard key={ins.id} insight={ins} />)}
            </div>
          </Section>
        )}
      </motion.div>
    )
  }

  // ---- Analyzed ----
  const ca = a.churn_analysis || {}
  const rec = a.all_recommendations?.[0]
  const churnBadge = CHURN_BADGE[ca.risk_level] || CHURN_BADGE.LOW
  const confPct = typeof a.confidence === 'number' ? Math.round(a.confidence * 100) : null
  const confColor = confPct >= 70 ? 'text-emerald-700 bg-emerald-50 border-emerald-200'
    : confPct >= 40 ? 'text-amber-700 bg-amber-50 border-amber-200'
    : 'text-gray-600 bg-gray-50 border-gray-200'
  const isPitch = rec?.is_low_confidence_pitch

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-5">
      <Link to="/customers" className="inline-flex items-center gap-1 text-[12px] font-semibold text-gray-500 hover:text-blue-600 transition-colors"><ArrowLeft size={14} /> Back to customers</Link>

      <AnimatePresence>
        {modal.open && <TraceModal open={modal.open} onClose={() => setModal({ ...modal, open: false })} trace={trace || a.trace} title={modal.title} content={modal.content} />}
      </AnimatePresence>

      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-[22px] font-extrabold text-gray-900 tracking-tight">{cs.company_name}</h1>
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <span className={`text-[10px] font-bold px-2.5 py-0.5 rounded-full uppercase ring-1 ring-inset ${churnBadge}`}>{ca.risk_level || 'LOW'} Churn</span>
            <span className="text-[10px] font-bold px-2.5 py-0.5 rounded-full bg-gray-100 text-gray-600 uppercase" title="Current product">{current}</span>
          </div>
          <p className="text-[12px] text-gray-500 mt-1.5">
            {[cs.industry && cs.industry !== 'Unknown' ? cs.industry : null, cs.seats ? `${cs.seats} seats` : null, cs.days_to_renewal != null ? `Renewal in ${cs.days_to_renewal} days` : null].filter(Boolean).join(' · ')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={run} disabled={running}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-blue-600 text-white text-[13px] font-semibold shadow-sm shadow-blue-500/20 hover:bg-blue-700 disabled:opacity-50 transition-all">
            {running ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}{running ? 'Running…' : 'Re-analyze'}
          </button>
          <button onClick={triggerEmail} disabled={emailLoading || emailSent || a?.decision_status !== 'qualified'}
            className={`inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-[13px] font-semibold shadow-sm transition-all ${emailSent ? 'bg-emerald-100 text-emerald-700 shadow-emerald-200/20' : 'bg-violet-600 text-white shadow-violet-500/20 hover:bg-violet-700'} disabled:opacity-50`}>
            {emailLoading ? <Loader2 size={16} className="animate-spin"/> : emailSent ? <CheckCircle2 size={16}/> : <Mail size={16}/>}
            {emailSent ? 'Sent!' : 'Send Email'}
          </button>
        </div>
      </div>

      {a.decision_status && a.decision_status !== 'qualified' && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3" role="status">
          <div className="flex items-center gap-2 text-amber-900 text-[13px] font-bold">
            <AlertTriangle size={16} /> No approved upsell — {a.decision_status.replaceAll('_', ' ')}
          </div>
          <p className="mt-1 text-[12px] text-amber-800">Traject did not find a verified recommendation for this account. Review the source evidence or improve the customer data before pitching a product.</p>
        </div>
      )}
      {!!a.evidence?.length && (
        <Section icon={ClipboardCheck} title="Evidence trail · imported data" iconColor="text-emerald-700">
          <p className="text-[12px] text-gray-500 mb-3">Source fields shown below are copied from this account's input data; they are not generated sales claims.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {a.evidence.slice(0, 8).map((e, i) => (
              <div key={i} className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">
                <div className="text-[10px] uppercase tracking-wide text-gray-500">{e.source} · {e.field}</div>
                <div className="text-[12px] font-medium text-gray-800 break-all">{String(e.value)}</div>
              </div>
            ))}
          </div>
        </Section>
      )}
      {a.data_gaps?.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3">
          <div className="flex items-center gap-2 mb-1.5"><AlertOctagon size={15} className="text-red-500" /><p className="text-[12.5px] font-bold text-red-800">Missing data — analysis below is limited</p></div>
          <ul className="space-y-1">{a.data_gaps.map((g, i) => <li key={i} className="text-[12px] text-red-700">• {g}</li>)}</ul>
        </div>
      )}
      {runError && <p className="text-[12px] font-semibold text-red-600">{runError}</p>}

      {/* Top 3 Recommendations */}
      <Section icon={Award} title="Top Recommendations" iconColor="text-violet-600"
        right={<button onClick={() => openModal('Why this recommendation?', a.all_recommendations?.[0]?.rationale)} className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-violet-600 transition-colors"><Brain size={14}/><span className="text-[11px] font-semibold">How we got here</span></button>}>
        <div className="space-y-3">
          {a.all_recommendations?.filter(r => r.recommended_product).slice(0, 3).map((rec, idx) => {
            const confPctR = typeof rec.confidence === 'number' ? Math.round(rec.confidence * 100) : null
            const confColorR = confPctR >= 70 ? 'text-emerald-700 bg-emerald-50 border-emerald-200'
              : confPctR >= 40 ? 'text-amber-700 bg-amber-50 border-amber-200'
              : 'text-gray-600 bg-gray-50 border-gray-200'
            const dealVal = rec.estimated_deal_value || rec.revenue_opportunity || 0
            const RANK_COLORS = [
              'from-violet-600 to-blue-600',
              'from-blue-500 to-cyan-500',
              'from-emerald-500 to-teal-500'
            ]
            // Clean rationale bullets
            const bullets = toBullets(rec.rationale)
            return (
              <div key={rec.id || idx} className={`rounded-xl border p-4 ${idx === 0 ? 'border-violet-200 bg-violet-50/30' : 'border-gray-100 bg-gray-50/50'}`}>
                <div className="flex items-start gap-3">
                  <div className={`h-7 w-7 rounded-full bg-gradient-to-br ${RANK_COLORS[idx]} text-white text-[11px] font-bold grid place-items-center shrink-0`}>{idx + 1}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-[14px] text-gray-900">{rec.recommended_product}</span>
                      {rec.recommendation_type && <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 uppercase">{rec.recommendation_type?.replace('_', ' ')}</span>}
                    </div>
                    <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                      {confPctR != null && <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full border ${confColorR}`}>{confPctR}% confidence</span>}
                      {dealVal > 0 && <span className="text-[11px] text-gray-500">Est. <span className="font-semibold text-gray-700">${Math.round(dealVal).toLocaleString()}/yr</span></span>}
                    </div>
                    {bullets.length > 0 && (
                      <ul className="mt-2 space-y-1 list-none">
                        {bullets.map((b, bi) => (
                          <li key={bi} className="flex items-start gap-1.5 text-[12px] text-gray-600 leading-relaxed">
                            <span className="text-violet-400 mt-0.5 shrink-0">•</span>
                            <span>{b}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
                {idx === 0 && (
                  <div className="flex items-center gap-2 mt-3 pt-3 border-t border-violet-100 flex-wrap">
                    <button onClick={() => sendFeedback('accepted')} disabled={feedback === 'accepted'}
                      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-semibold border transition-colors ${feedback === 'accepted' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'text-gray-600 border-gray-200 hover:bg-gray-50'}`}>
                      {feedback === 'accepted' ? <CheckCircle2 size={13}/> : <ThumbsUp size={13}/>} Accept
                    </button>
                    <button onClick={() => sendFeedback('rejected')} disabled={feedback === 'rejected'}
                      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-semibold border transition-colors ${feedback === 'rejected' ? 'bg-red-50 text-red-700 border-red-200' : 'text-gray-600 border-gray-200 hover:bg-gray-50'}`}>
                      <ThumbsDown size={13}/> Not a fit
                    </button>
                    <div className="flex-1"/>
                    {ca.risk_level === 'HIGH' && (
                      <button onClick={() => setShowMeetingScheduler(true)}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-semibold text-gray-600 border border-gray-200 hover:bg-gray-50 transition-colors">
                        <Calendar size={13}/> Schedule Meeting
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })}
          {(!a.all_recommendations?.some(r => r.recommended_product)) && (
            <div>
              <p className="text-[14px] text-gray-600 mb-2">No upsell is a good fit right now — here's what to do instead:</p>
              {(() => {
                const detail = a.retention_action_detail
                const meta = RETENTION_ACTION_META[detail?.action_type] || RETENTION_ACTION_META.account_review
                const ActionIcon = meta.icon
                return (
                  <div className="flex items-start gap-3 bg-white rounded-lg border border-gray-200 p-3">
                    <div className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center ring-1 ring-inset ${meta.className}`}>
                      <ActionIcon size={15}/>
                    </div>
                    <div className="min-w-0">
                      <span className={`inline-block text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ring-1 ring-inset mb-1 ${meta.className}`}>{meta.label}</span>
                      <p className="text-[13px] text-gray-700">{a.retention_action || ca.explanation}</p>
                      {detail?.talking_point && (
                        <p className="text-[12px] text-gray-400 mt-1">Talking point: {detail.talking_point}</p>
                      )}
                    </div>
                  </div>
                )
              })()}
            </div>
          )}
        </div>
      </Section>

      {/* What the data shows — insights as bullet-point metric cards */}
      {a.insights?.length > 0 && (
        <Section icon={BarChart2} title="What the data shows" iconColor="text-blue-600">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {a.insights.map(ins => (
              <div key={ins.id} className="rounded-xl border border-gray-100 bg-white p-4 hover:border-gray-200 hover:shadow-sm transition-all">
                <div className="flex items-start gap-2 mb-2">
                  {ins.category === 'risk' && <AlertTriangle size={14} className="text-red-500 mt-0.5 shrink-0"/>}
                  {ins.category === 'revenue' && <TrendingUp size={14} className="text-emerald-600 mt-0.5 shrink-0"/>}
                  {ins.category === 'usage' && <BarChart2 size={14} className="text-violet-600 mt-0.5 shrink-0"/>}
                  {!['risk','revenue','usage'].includes(ins.category) && <Sparkles size={14} className="text-blue-500 mt-0.5 shrink-0"/>}
                  <div className="flex-1">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <h4 className="text-[13px] font-bold text-gray-900">{ins.title}</h4>
                      <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full uppercase ${
                        ins.category === 'risk' ? 'bg-red-100 text-red-700' :
                        ins.category === 'revenue' ? 'bg-emerald-100 text-emerald-700' :
                        ins.category === 'usage' ? 'bg-violet-100 text-violet-700' :
                        'bg-blue-100 text-blue-700'
                      }`}>{ins.category}</span>
                    </div>
                  </div>
                </div>
                {/* Summary as bullet points */}
                <ul className="space-y-1 mb-3">
                  {toBullets(ins.summary).map((pt, pi) => (
                    <li key={pi} className="flex items-start gap-1.5 text-[12px] text-gray-600 leading-relaxed">
                      <span className="text-blue-400 mt-0.5 shrink-0">•</span>
                      <span>{pt}</span>
                    </li>
                  ))}
                </ul>
                {/* Metric chips */}
                {ins.metrics?.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {ins.metrics.map((m, mi) => (
                      <div key={mi} className="bg-gray-50 rounded-lg px-2.5 py-1.5 border border-gray-100">
                        <p className="text-[9px] font-bold uppercase tracking-wider text-gray-400">{m.label}</p>
                        <p className="text-[13px] font-bold text-gray-800">{m.value != null ? (typeof m.value === 'number' ? m.value.toLocaleString() : m.value) : '—'}{m.unit ? ` ${m.unit}` : ''}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      <AnimatePresence>
        {showMeetingScheduler && <MeetingScheduler customer={cs} onClose={() => setShowMeetingScheduler(false)} />}
      </AnimatePresence>
    </motion.div>
  )
}
