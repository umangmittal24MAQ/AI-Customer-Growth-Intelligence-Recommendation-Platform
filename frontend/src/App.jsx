import { useEffect, useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Topbar from './components/Topbar'
import Dashboard from './pages/Dashboard'
import CustomerList from './pages/CustomerList'
import CustomerDetail from './pages/CustomerDetail'
import TenantLogin from './components/TenantLogin'
import TenantSignup from './components/TenantSignup'
import ChatAgent from './pages/ChatAgent'
import Settings from './pages/Settings'
import { hasTenantCredentials } from './api/tenantSession'
import { AppDataProvider, useAppData } from './context/AppDataContext'

function AppShell() {
  const { prefetch } = useAppData()
  useEffect(() => { prefetch() }, [])
  return (
    <div className="min-h-screen traject-app">
      <Sidebar />
      <div className="md:pl-[244px] flex flex-col min-h-screen">
        <Topbar />
        <main className="flex-1 p-4 sm:p-6 lg:p-8 pb-24 md:pb-8">
          <div className="max-w-[1480px] mx-auto">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/customers" element={<CustomerList />} />
              <Route path="/customers/:id" element={<CustomerDetail />} />
              <Route path="/chat" element={<ChatAgent />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </div>
        </main>
      </div>
    </div>
  )
}

export default function App() {
  const [signedIn, setSignedIn] = useState(hasTenantCredentials())
  const [authView, setAuthView] = useState('login')

  useEffect(() => {
    const onUnauthorized = () => setSignedIn(false)
    window.addEventListener('traject:tenant-unauthorized', onUnauthorized)
    return () => window.removeEventListener('traject:tenant-unauthorized', onUnauthorized)
  }, [])

  if (!signedIn) {
    return (
      <AppDataProvider>
        {authView === 'signup'
          ? <TenantSignup onSwitchToLogin={() => setAuthView('login')} />
          : <TenantLogin onSignedIn={() => setSignedIn(true)} onSwitchToSignup={() => setAuthView('signup')} />}
      </AppDataProvider>
    )
  }

  return (
    <AppDataProvider>
      <AppShell />
    </AppDataProvider>
  )
}
