import axios from 'axios'
import { getTenantCredentials, clearTenantCredentials } from './tenantSession'

const api = axios.create({ baseURL: '/api', timeout: 300000 })

// Every backend route now depends on get_current_tenant (see
// backend/app/auth.py) and requires these two headers -- attach them here,
// in one place, instead of repeating it on every call below.
api.interceptors.request.use((config) => {
  const { tenantId, apiKey } = getTenantCredentials()
  if (tenantId && apiKey) {
    config.headers['X-Tenant-Id'] = tenantId
    config.headers['X-API-Key'] = apiKey
  }
  return config
})

// A 403 here means the stored tenant_id/API key pair is wrong or revoked
// (see auth.get_current_tenant) -- clear it so the login gate reappears
// instead of the app silently re-sending a key that will never work.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 403) {
      clearTenantCredentials()
      window.dispatchEvent(new Event('traject:tenant-unauthorized'))
    }
    return Promise.reject(error)
  }
)

export const getCustomers = () => api.get('/customers').then(r => r.data)
export const getCustomer = (id) => api.get(`/customers/${id}`).then(r => r.data)
export const getCustomerAnalysis = (id) => api.get(`/customers/${id}/analysis`).then(r => r.data)
export const getDataStatus = () => api.get('/data-status').then(r => r.data)
export const getCatalog = () => api.get('/catalog').then(r => r.data)
export const generateRecommendations = (customerId, segment) => {
  const p = new URLSearchParams()
  if (customerId) p.set('customer_id', customerId)
  if (segment) p.set('segment', segment)
  const q = p.toString() ? `?${p}` : ''
  return api.post(`/generate-recommendations${q}`).then(r => r.data)
}
export const getRecommendations = (cid) => api.get(`/recommendations/${cid}`).then(r => r.data)
export const getAnalyticsSummary = () => api.get('/analytics/summary').then(r => r.data)
export const submitFeedback = (id, status) => api.post(`/recommendations/${id}/feedback`, { status }).then(r => r.data)

// Email + password auth (see backend app/accounts.py). Both endpoints
// return {tenant_id, api_key, ...} -- store api_key in sessionStorage same
// as before, the user never sees or types it; the password is the real
// credential now, verified server-side.
export const signupTenant = (clientName, email, password, confirmPassword, domain) =>
  axios.post('/auth/signup', {
    client_name: clientName,
    email,
    password,
    confirm_password: confirmPassword,
    domain: domain || null,
  }).then(r => r.data)

export const loginTenant = (email, password) =>
  axios.post('/auth/login', { email, password }).then(r => r.data)

export const sendRecommendationEmail = (customerId, toEmail, senderName) =>
  api.post(`/customers/${customerId}/send-recommendation-email`, { to_email: toEmail, sender_name: senderName }).then(r => r.data)
export const triggerPowerAutomateEmail = (customerId) =>
  api.post(`/customers/${customerId}/trigger-email`).then(r => r.data)

export const scheduleMeeting = (customerId, payload) =>
  api.post(`/customers/${customerId}/schedule-meeting`, payload).then(r => r.data)

export const addCatalogProduct = (product) =>
  api.post('/catalog/products', product).then(r => r.data)

export const deleteCatalogProduct = (productId) =>
  api.delete(`/catalog/products/${productId}`).then(r => r.data)

export const updateCatalogProduct = (productId, updates) =>
  api.patch(`/catalog/products/${productId}`, updates).then(r => r.data)

export const getFeatureWeights = () =>
  api.get('/tenant/feature-weights').then(r => r.data)

export const setFeatureWeights = (weights) =>
  api.post('/tenant/feature-weights', { weights }).then(r => r.data)

export const sendChatMessage = (message, conversationId = null, customerId = null) =>
  api.post('/chat', { message, conversation_id: conversationId, hint_customer_id: customerId }).then(r => r.data)

export const getChatSessions = () =>
  api.get('/chat/sessions').then(r => r.data)

export const getChatSession = (conversationId) =>
  api.get(`/chat/sessions/${conversationId}`).then(r => r.data)

export const listChatSessions = () =>
  api.get('/chat/sessions').then(r => r.data)

export const deleteChatSession = (conversationId) =>
  api.delete(`/chat/sessions/${conversationId}`).then(r => r.data)

export const batchSendEmails = (toEmailMap, senderName) =>
  api.post('/batch/send-emails', { to_email_map: toEmailMap, sender_name: senderName }).then(r => r.data)

export default api
