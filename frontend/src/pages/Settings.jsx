import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Save, Loader2, CheckCircle2, Sliders } from 'lucide-react'
import { getFeatureWeights, setFeatureWeights } from '../api/client'

const FEATURES = [
  { key: 'churn_risk', label: 'Churn Risk', desc: 'Weight given to the churn risk signal' },
  { key: 'renewal_date', label: 'Renewal Date', desc: 'Importance of approaching renewal deadlines' },
  { key: 'usage_trend', label: 'Usage Trend', desc: 'Recent usage growth or decline' },
  { key: 'ticket_count', label: 'Support Tickets', desc: 'Open/unresolved support ticket signals' },
  { key: 'seats', label: 'Seat Count', desc: 'Number of seats (deal size indicator)' },
  { key: 'feature_usage_score', label: 'Feature Adoption', desc: 'How actively the customer uses features' },
]

function WeightSlider({ feature, weight, onChange }) {
  const color = weight > 1.5 ? 'text-[#326c3d]' : weight < 0.5 ? 'text-gray-400' : 'text-gray-700'
  return (
    <div className="traject-card bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-2">
        <div>
          <p className="text-sm font-semibold text-gray-900">{feature.label}</p>
          <p className="text-xs text-gray-400">{feature.desc}</p>
        </div>
        <span className={`text-sm font-extrabold tabular-nums ${color}`}>{weight.toFixed(1)}×</span>
      </div>
      <input type="range" min="0" max="3" step="0.1" value={weight}
        onChange={e=>onChange(parseFloat(e.target.value))}
        className="w-full h-2 accent-[#79ad48] cursor-pointer"/>
      <div className="flex justify-between text-[10px] text-gray-300 mt-1">
        <span>0× (ignore)</span><span>1× (normal)</span><span>3× (max)</span>
      </div>
    </div>
  )
}

export default function Settings() {
  const [weights, setWeightsState] = useState(Object.fromEntries(FEATURES.map(f=>[f.key,1.0])))
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  useEffect(()=>{
    getFeatureWeights().then(res=>{
      if (res.weights && Object.keys(res.weights).length>0)
        setWeightsState(prev=>({...prev,...res.weights}))
    }).catch(()=>{}).finally(()=>setLoading(false))
  },[])

  const handleSave = async()=>{
    setSaving(true); setError(''); setSaved(false)
    try { await setFeatureWeights(weights); setSaved(true); setTimeout(()=>setSaved(false),3000) }
    catch(e) { setError(e.response?.data?.detail||'Failed to save.') }
    finally { setSaving(false) }
  }

  if (loading) return <div className="flex items-center justify-center py-20"><Loader2 size={24} className="animate-spin text-gray-400"/></div>

  return (
    <motion.div initial={{opacity:0}} animate={{opacity:1}} className="space-y-6 max-w-2xl">
      <div>
        <p className="text-[10px] font-extrabold uppercase tracking-[.2em] text-[#708075] mb-2">Workspace control / 04</p>
        <h1 className="text-[30px] sm:text-[34px] font-extrabold text-[#1a2923] tracking-tight">Intelligence settings<span className="text-[#7ba93c]">.</span></h1>
        <p className="text-[13px] text-[#718175] mt-1">Tune how Traject weighs churn, adoption and expansion signals.</p>
      </div>
      <div className="traject-card bg-white rounded-2xl border border-gray-200/60 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-2">
          <Sliders size={16} className="text-[#48833c]"/>
          <h2 className="text-sm font-bold text-gray-900">Feature Weights</h2>
        </div>
        <div className="p-5 space-y-3">
          <p className="text-xs text-gray-500 mb-4">Values above 1× increase importance; below 1× reduces it; 0× ignores the signal entirely.</p>
          {FEATURES.map(f=>(
            <WeightSlider key={f.key} feature={f} weight={weights[f.key]??1.0}
              onChange={v=>setWeightsState(prev=>({...prev,[f.key]:v}))}/>
          ))}
        </div>
        <div className="px-5 py-4 border-t border-gray-100 flex items-center justify-between">
          <button onClick={()=>setWeightsState(Object.fromEntries(FEATURES.map(f=>[f.key,1.0])))} className="text-sm text-gray-500 hover:text-gray-700 font-medium">Reset to defaults</button>
          <div className="flex items-center gap-3">
            {saved && <motion.span initial={{opacity:0}} animate={{opacity:1}} className="flex items-center gap-1.5 text-sm text-emerald-600 font-semibold"><CheckCircle2 size={14}/>Saved!</motion.span>}
            {error && <p className="text-sm text-red-600">{error}</p>}
            <button onClick={handleSave} disabled={saving}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50 transition-colors">
              {saving ? <><Loader2 size={14} className="animate-spin"/>Saving…</> : <><Save size={14}/>Save Changes</>}
            </button>
          </div>
        </div>
      </div>
    </motion.div>
  )
}
