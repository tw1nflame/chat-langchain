// Prefer Next.js public env var, fallback to Vite-style or localhost. Avoid using `import.meta` (not supported by Next bundler).
const API_BASE =
  (typeof process !== 'undefined' && process.env && process.env.NEXT_PUBLIC_API_BASE_URL) ||
  (typeof process !== 'undefined' && process.env && process.env.VITE_API_BASE_URL) ||
  "http://localhost:8000"

import { supabase } from "../lib/supabaseClient"

async function getAuthHeaders() {
  try {
  const { data } = await supabase.auth.getSession()
  const session = data?.session
  console.log('[chat.api] current supabase session exists:', !!session)
    if (session && session.access_token) {
      const headers = {
        Authorization: `Bearer ${session.access_token}`,
      }
      // Log a short masked preview so devs can see a token is present without exposing it
      try {
        const token = session.access_token
        const masked = `Bearer <REDACTED> len=${token.length}`
        console.log('[chat.api] got access token:', masked)
      } catch (e) {
        // ignore
      }
      return headers
    }
  } catch (e) {
    // ignore and return empty headers
  }
  return {}
}

// Отправить сообщение в чат и получить ответ ассистента
export const sendMessage = async (chatId, content, files = []) => {
  const formData = new FormData()
  formData.append("role", "user")
  formData.append("content", content)

  // Добавляем файлы в FormData (если есть)
  if (files && files.length > 0) {
    files.forEach((file) => {
      formData.append("files", file)
    })
  }

  const authHeaders = await getAuthHeaders()

  // Debug logging: show endpoint, headers and form data entries
  try {
    console.log("[chat.api] sendMessage -> url:", `${API_BASE}/api/v1/chats/${chatId}/messages`)
    // Redact Authorization header in logs
    const safeHeaders = { ...authHeaders }
    if (safeHeaders.Authorization) safeHeaders.Authorization = "<REDACTED>"
    console.log("[chat.api] authHeaders:", safeHeaders)
    // Avoid logging full form data contents (may include sensitive user input or files)
    for (const pair of formData.entries()) {
      console.log("[chat.api] formData entry:", pair[0], pair[1] && pair[1].name ? `<File ${pair[1].name}>` : (pair[0] === 'content' ? '<CONTENT>' : '<VALUE>'))
    }
  } catch (e) {
    console.warn("[chat.api] logging failed:", e)
  }

  const response = await fetch(`${API_BASE}/api/v1/chats/${chatId}/messages`, {
    method: "POST",
    body: formData,
    headers: authHeaders,
  })

  // Log response status and body (or JSON)
  let responseText = null
  try {
    responseText = await response.text()
  } catch (e) {
    console.warn("[chat.api] could not read response text:", e)
  }
  console.log("[chat.api] response status:", response.status, "body:", responseText)

  if (!response.ok) {
    // Check if this is a "chat deleted during processing" error - don't log as error
    const isChatDeletedError = response.status === 404 && 
      responseText && responseText.includes('Chat was deleted during processing')
    
    if (!isChatDeletedError) {
      console.error("[chat.api] Server error:", response.status, responseText)
    } else {
      console.log("[chat.api] Chat was deleted during processing (expected):", response.status)
    }
    
    // Create a custom error for chat deleted case
    let errorMessage
    try {
      const jsonErr = JSON.parse(responseText)
      errorMessage = isChatDeletedError ? 
        `ChatDeletedError: ${jsonErr.detail}` : 
        JSON.stringify(jsonErr)
    } catch (e) {
      errorMessage = `HTTP error! status: ${response.status} body: ${responseText}`
    }
    
    throw new Error(errorMessage)
  }

  let result = {}
  try {
    result = JSON.parse(responseText || "{}")
  } catch (e) {
    console.warn("[chat.api] failed to parse JSON response, falling back to empty object", e)
  }

  // Возвращаем оба сообщения из API (поддерживает старый интерфейс)
  return {
    userMessage: result.user_message,
    assistantMessage: result.assistant_message,
  }
}

// Получить все сообщения чата
export const getChatMessages = async (chatId) => {
  const authHeaders = await getAuthHeaders()
  // Debug: log which headers will be sent (redacted)
  try {
    const safe = { ...authHeaders }
    if (safe.Authorization) safe.Authorization = `<REDACTED: len=${String(safe.Authorization).split(' ').pop()?.length || 'unknown'}>`
    console.log('[chat.api] getChatMessages ->', { url: `${API_BASE}/api/v1/chats/${chatId}/messages`, headers: safe })
  } catch (e) {
    console.warn('[chat.api] failed to log headers for getChatMessages', e)
  }
  const response = await fetch(`${API_BASE}/api/v1/chats/${chatId}/messages`, {
    headers: authHeaders,
  })

  // Debug: log status and body for troubleshooting
  let bodyText = null
  try {
    bodyText = await response.text()
  } catch (e) {
    console.warn("[chat.api] could not read messages response text:", e)
  }
  console.log("[chat.api] getChatMessages chatId:", chatId, "status:", response.status, "body:", bodyText)

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      console.debug(`[chat.api] getChatMessages: unauthorized (status ${response.status}), returning empty array`)
      return []
    }
    throw new Error(`HTTP error! status: ${response.status} body: ${bodyText}`)
  }

  try {
    return JSON.parse(bodyText || "[]")
  } catch (e) {
    console.warn("[chat.api] failed to parse messages JSON, returning empty array", e)
    return []
  }
}

// Создать новый чат
export const createChat = async (title = null) => {
  const authHeaders = await getAuthHeaders()
  const headers = {
    "Content-Type": "application/json",
    ...authHeaders,
  }
  try {
    const safe = { ...headers }
    if (safe.Authorization) safe.Authorization = `<REDACTED: len=${String(safe.Authorization).split(' ').pop()?.length || 'unknown'}>`
    console.log('[chat.api] createChat ->', { url: `${API_BASE}/api/v1/chats`, method: 'POST', headers: safe })
  } catch (e) {
    console.warn('[chat.api] failed to log headers for createChat', e)
  }

  const response = await fetch(`${API_BASE}/api/v1/chats`, {
    method: "POST",
    headers,
    body: JSON.stringify({ title }),
  })

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`)
  }

  return await response.json()
}

// Получить все чаты
export const getChats = async () => {
  const authHeaders = await getAuthHeaders()
  try {
    const safe = { ...authHeaders }
    if (safe.Authorization) safe.Authorization = `<REDACTED: len=${String(safe.Authorization).split(' ').pop()?.length || 'unknown'}>`
    console.log('[chat.api] getChats ->', { url: `${API_BASE}/api/v1/chats`, headers: safe })
  } catch (e) {
    console.warn('[chat.api] failed to log headers for getChats', e)
  }
  const response = await fetch(`${API_BASE}/api/v1/chats`, {
    headers: authHeaders,
  })

  if (!response.ok) {
    // If unauthenticated, return empty list instead of throwing to avoid
    // noisy errors during page load before session restore completes.
    if (response.status === 401 || response.status === 403) {
      console.debug(`[chat.api] getChats: unauthorized (status ${response.status}), returning empty list`) 
      return []
    }
    // For other errors, surface them so callers can decide how to handle
    throw new Error(`HTTP error! status: ${response.status}`)
  }

  try {
    return await response.json()
  } catch (e) {
    console.warn('[chat.api] getChats: failed to parse JSON, returning empty list', e)
    return []
  }
}

// Удалить чат
export const deleteChat = async (chatId) => {
  const authHeaders = await getAuthHeaders()
  try {
    const safe = { ...authHeaders }
    if (safe.Authorization) safe.Authorization = `<REDACTED: len=${String(safe.Authorization).split(' ').pop()?.length || 'unknown'}>`
    console.log('[chat.api] deleteChat ->', { url: `${API_BASE}/api/v1/chats/${chatId}`, method: 'DELETE', headers: safe })
  } catch (e) {
    console.warn('[chat.api] failed to log headers for deleteChat', e)
  }
  const response = await fetch(`${API_BASE}/api/v1/chats/${chatId}`, {
    method: 'DELETE',
    headers: authHeaders,
  })
  if (!response.ok) {
    let body = null
    try {
      body = await response.text()
    } catch (e) {}
    throw new Error(`Failed to delete chat ${chatId}: ${response.status} ${body || ''}`)
  }
  return true
}
