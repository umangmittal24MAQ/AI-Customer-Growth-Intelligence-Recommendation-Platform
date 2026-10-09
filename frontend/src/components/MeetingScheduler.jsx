import { useState } from 'react'
import { motion } from 'framer-motion'
import { X, Calendar, Clock, Mail, FileText, Loader2, CheckCircle2, ExternalLink, AlertCircle } from 'lucide-react'
import { scheduleMeeting } from '../api/client'

export default function MeetingScheduler({ customer, onClose }) {
  const [form, setForm] = useState({
    title: `Discussion with ${customer?.company_name || customer?.customer_name || 'Customer'}`,
    date: '',
    time: '10:00',
    attendeeEmail: '',
    duration: 30,
    agenda: '',
    sendEmail: true,
  })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!form.date || !form.attendeeEmail) { setError('Date and attendee email are required.'); return }
    setError(''); setLoading(true)
    try {
      const datetimeUtc = `${form.date}T${form.time}:00`
      const res = await scheduleMeeting(customer.customer_id, {
        title: form.title,
        datetime_utc: datetimeUtc,
        attendee_email: form.attendeeEmail,
        duration_minutes: form.duration,
        agenda: form.agenda || undefined,
        send_email: form.sendEmail,
      })
      setResult(res)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to schedule. Check Google Calendar configuration.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-900/50 backdrop-blur-sm" onClick={onClose}>
      <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.95 }}
        onClick={e => e.stopPropagation()}
        className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between bg-gradient-to-r from-blue-50 to-indigo-50">
          <div className="flex items-center gap-2">
            <Calendar size={18} className="text-blue-600" />
            <h3 className="font-bold text-gray-900">Schedule Meeting</h3>
          </div>
          <button onClick={onClose} className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-white/60 rounded-lg transition-colors"><X size={16} /></button>
        </div>
        {result ? (
          <div className="p-6 flex flex-col items-center text-center py-8">
            <CheckCircle2 size={48} className="text-emerald-500 mb-3" />
            <h4 className="text-lg font-bold text-gray-900 mb-1">{result.status === 'created' ? 'Meeting scheduled!' : 'Meeting details ready'}</h4>
            {result.status === 'created'
              ? <p className="text-sm text-gray-500 mb-4">Google Calendar event created.</p>
              : <p className="text-sm text-amber-600 mb-4">{result.fallback_message}</p>}
            <div className="bg-gray-50 rounded-xl p-4 w-full text-left space-y-2 text-sm">
              <p><strong>Title:</strong> {result.title}</p>
              <p><strong>Time:</strong> {result.meeting_datetime_utc}</p>
              <p><strong>Duration:</strong> {result.duration_minutes} min</p>
              <p><strong>Attendee:</strong> {result.attendee_email}</p>
              {result.meet_link && <a href={result.meet_link} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-blue-600 font-semibold hover:underline mt-1"><ExternalLink size={14} />Join Google Meet</a>}
            </div>
            <button onClick={onClose} className="mt-4 px-5 py-2 bg-gray-900 text-white rounded-xl text-sm font-semibold hover:bg-gray-800 transition-colors">Done</button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Meeting Title</label>
              <input value={form.title} onChange={e => setForm({...form, title: e.target.value})} className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Date</label>
                <input type="date" value={form.date} onChange={e => setForm({...form, date: e.target.value})} className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Time (UTC)</label>
                <input type="time" value={form.time} onChange={e => setForm({...form, time: e.target.value})} className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Attendee Email</label>
              <input type="email" value={form.attendeeEmail} onChange={e => setForm({...form, attendeeEmail: e.target.value})} placeholder="attendee@company.com" className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Duration</label>
              <select value={form.duration} onChange={e => setForm({...form, duration: parseInt(e.target.value)})} className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value={15}>15 minutes</option><option value={30}>30 minutes</option>
                <option value={45}>45 minutes</option><option value={60}>1 hour</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Agenda (optional)</label>
              <textarea value={form.agenda} onChange={e => setForm({...form, agenda: e.target.value})} rows={3} placeholder="What will you discuss?" className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
            </div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={form.sendEmail} onChange={e => setForm({...form, sendEmail: e.target.checked})} className="w-4 h-4 text-blue-600 rounded" />
              <span className="text-sm text-gray-600">Send invite email to attendee</span>
            </label>
            {error && <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-xl px-3 py-2.5"><AlertCircle size={14} className="text-red-500 shrink-0" /><p className="text-sm text-red-600">{error}</p></div>}
            <div className="flex gap-3 pt-2">
              <button type="button" onClick={onClose} className="flex-1 border border-gray-200 text-gray-700 rounded-xl py-2.5 text-sm font-semibold hover:bg-gray-50 transition-colors">Cancel</button>
              <button type="submit" disabled={loading} className="flex-1 bg-blue-600 text-white rounded-xl py-2.5 text-sm font-semibold hover:bg-blue-700 disabled:opacity-50 transition-colors flex items-center justify-center gap-2">
                {loading ? <><Loader2 size={14} className="animate-spin" />Scheduling…</> : <><Calendar size={14} />Schedule Meeting</>}
              </button>
            </div>
          </form>
        )}
      </motion.div>
    </div>
  )
}
