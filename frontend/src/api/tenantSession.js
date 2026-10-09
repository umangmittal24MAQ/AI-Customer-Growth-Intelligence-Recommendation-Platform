// Every backend request now requires X-Tenant-Id / X-API-Key (see
// backend/app/auth.py). This module is the single place that stores those
// two values for the current browser session and hands them to client.js's
// axios interceptor -- nothing else in the app should read/write these
// directly.
//
// Kept in sessionStorage (not localStorage) so a shared/kiosk machine
// doesn't silently keep a previous tenant's key logged in after the tab
// closes.

const TENANT_ID_KEY = 'traject.tenantId'
const API_KEY_KEY = 'traject.apiKey'

export function getTenantCredentials() {
  return {
    tenantId: sessionStorage.getItem(TENANT_ID_KEY) || '',
    apiKey: sessionStorage.getItem(API_KEY_KEY) || '',
  }
}

export function setTenantCredentials(tenantId, apiKey) {
  sessionStorage.setItem(TENANT_ID_KEY, tenantId)
  sessionStorage.setItem(API_KEY_KEY, apiKey)
}

export function clearTenantCredentials() {
  sessionStorage.removeItem(TENANT_ID_KEY)
  sessionStorage.removeItem(API_KEY_KEY)
}

export function hasTenantCredentials() {
  const { tenantId, apiKey } = getTenantCredentials()
  return Boolean(tenantId && apiKey)
}
