import { createContext, useContext, useState, useCallback, useEffect } from 'react'
import { getCustomers, getAnalyticsSummary, getDataStatus, getCatalog } from '../api/client'

const AppDataContext = createContext(null)

export function AppDataProvider({ children }) {
  const [customers, setCustomers] = useState([])
  const [analytics, setAnalytics] = useState(null)
  const [dataStatus, setDataStatus] = useState(null)
  const [catalog, setCatalog] = useState(null)
  const [loading, setLoading] = useState(false)
  const [initialized, setInitialized] = useState(false)

  const prefetch = useCallback(async () => {
    setLoading(true)
    try {
      const [customersRes, analyticsRes, dataStatusRes, catalogRes] = await Promise.allSettled([
        getCustomers(),
        getAnalyticsSummary(),
        getDataStatus(),
        getCatalog(),
      ])
      if (customersRes.status === 'fulfilled') setCustomers(customersRes.value || [])
      if (analyticsRes.status === 'fulfilled') setAnalytics(analyticsRes.value)
      if (dataStatusRes.status === 'fulfilled') setDataStatus(dataStatusRes.value)
      if (catalogRes.status === 'fulfilled') setCatalog(catalogRes.value)
    } catch (e) {
      console.warn('AppDataContext prefetch error:', e)
    } finally {
      setLoading(false)
      setInitialized(true)
    }
  }, [])

  const refresh = useCallback(async (key) => {
    try {
      if (!key || key === 'customers') { const r = await getCustomers(); setCustomers(r || []) }
      if (!key || key === 'analytics') { const r = await getAnalyticsSummary(); setAnalytics(r) }
      if (!key || key === 'dataStatus') { const r = await getDataStatus(); setDataStatus(r) }
      if (!key || key === 'catalog') { const r = await getCatalog(); setCatalog(r) }
    } catch (e) {
      console.warn('AppDataContext refresh error:', e)
    }
  }, [])

  // First sign-in starts the tenant CSV bootstrap in a backend thread.
  // Poll only while its first catalog/customers are missing: otherwise the
  // initial empty response can remain on screen until a manual page reload.
  useEffect(() => {
    if (!initialized || dataStatus?.can_run_analysis || customers.length > 0) return undefined
    let attempts = 0
    let inFlight = false
    const timer = setInterval(async () => {
      if (inFlight) return
      if (++attempts > 24) { clearInterval(timer); return }
      inFlight = true
      try {
        const status = await getDataStatus()
        if (status?.customers > 0 || status?.can_run_analysis) {
          await refresh()
          if (status.can_run_analysis || attempts > 23) clearInterval(timer)
        }
      } catch (error) {
        console.warn('Traject onboarding sync:', error)
      } finally { inFlight = false }
    }, 4000)
    return () => clearInterval(timer)
  }, [initialized, dataStatus?.can_run_analysis, customers.length, refresh])

  return (
    <AppDataContext.Provider value={{ customers, analytics, dataStatus, catalog, loading, initialized, prefetch, refresh }}>
      {children}
    </AppDataContext.Provider>
  )
}

export function useAppData() {
  const ctx = useContext(AppDataContext)
  if (!ctx) throw new Error('useAppData must be used inside AppDataProvider')
  return ctx
}
