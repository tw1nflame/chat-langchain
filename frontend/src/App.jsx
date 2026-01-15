"use client"

import { useState, useEffect } from "react"
import { useRef } from "react"
import Sidebar from "./components/Sidebar"
import ChatWindow from "./components/ChatWindow"
import LoginPage from "./components/LoginPage"
import RegisterPage from "./components/RegisterPage"
import { getChats, getChatMessages, createChat } from "./api/chat"
import { supabase, getCurrentSession } from "./lib/supabaseClient"

// Генерация UUID v4
function generateUUID() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c == "x" ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

function App() {
  // Состояние аутентификации
  const [user, setUser] = useState(null)
  const [authLoaded, setAuthLoaded] = useState(false)
  const [authPage, setAuthPage] = useState("login") // 'login' или 'register'
  const [loadingChats, setLoadingChats] = useState(false)

  // Состояние чатов
  const [chats, setChats] = useState({})
  const [activeChat, setActiveChat] = useState(null)
  const [loadingChatId, setLoadingChatId] = useState(null)

  // Track whether the initial server load has been performed (persisted across renders)
  const initialLoadDoneRef = useRef(false)

  // Функции аутентификации
  const handleLogin = (userData) => {
    setUser(userData)
    // Server chats will be loaded by the useEffect when user state changes
  }

  const handleRegister = (userData) => {
    setUser(userData)
    // Server chats will be loaded by the useEffect when user state changes
  }

  const handleLogout = async () => {
    // Sign out from Supabase and clear UI state
    try {
      await supabase.auth.signOut()
    } catch (e) {
      console.warn('[App] supabase.signOut failed', e)
    }

    // Remove persisted Supabase session keys (best-effort)
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        Object.keys(window.localStorage).forEach((k) => {
          if (k.startsWith('supabase.auth') || k.includes('supabase')) {
            window.localStorage.removeItem(k)
          }
        })
      }
    } catch (e) {
      console.warn('[App] clearing localStorage failed', e)
    }

    // Очищаем пустые локальные чаты перед выходом
    cleanupEmptyLocalChats()

    // Reset the initial-load marker so a subsequent sign-in will re-run
    // the server chat loader and create an initial chat if needed.
    try {
      initialLoadDoneRef.current = false
    } catch (e) {}

    setUser(null)
    setChats({})
    setActiveChat(null)
    setAuthPage('login')
  }

  const handleDeleteChat = async (chatId) => {
    try {
      const chatObj = chats[chatId]
      
      // optimistic UI: remove immediately
      setChats((prev) => {
        const copy = { ...prev }
        delete copy[chatId]
        return copy
      })
      if (activeChat === chatId) {
        setActiveChat(null)
      }
      
      // Only delete from server if chat has server_id and is persisted
      // Local chats without server_id or not persisted only exist in browser state
      if (chatObj && chatObj.server_id && chatObj.persisted) {
        await import("./api/chat").then(({ deleteChat }) => deleteChat(chatObj.server_id))
        console.log('[App] Chat deleted from server:', chatObj.server_id)
      } else {
        console.log('[App] Deleted local-only chat:', chatId, 'server_id:', chatObj?.server_id, 'persisted:', chatObj?.persisted)
      }
    } catch (e) {
      console.error('[App] failed to delete chat', chatId, e)
      // on error, re-fetch chat list
      try {
        const serverChats = await getChats()
        console.debug('[App] fetched serverChats (delete-refresh):', serverChats)
        const mapped = {}
        for (const c of serverChats) {
          const previewRole = c.last_message_role || (c.last_message ? 'assistant' : null)
          const titleFromFirst = c.first_message ? (c.first_message.length > 60 ? c.first_message.slice(0, 60) + '...' : c.first_message) : null
          const previewFromLast = c.last_message ? (c.last_message.length > 60 ? c.last_message.slice(0, 60) + '...' : c.last_message) : null
          const defaultTitles = ['Новый чат', '', 'Чат с ассистентом']
          const useServerTitle = c.title && !defaultTitles.includes(c.title)
          mapped[c.id] = {
            id: c.id,
            server_id: c.id,
            // Prefer server title if it's meaningful, otherwise prefer first_message as header
            title: useServerTitle ? c.title : (titleFromFirst || 'Новый чат'),
            // Preview uses the last_message (most recent)
            messages: c.last_message ? [{ id: c.id + "-preview", role: previewRole, content: c.last_message, timestamp: c.created_at ? new Date(c.created_at) : new Date() }] : [],
            preview: Boolean(c.last_message),
            createdAt: c.created_at ? new Date(c.created_at) : new Date(),
            persisted: true, // Server chats are always persisted
          }
        }
        setChats(mapped)
      } catch (err) {
        console.warn('[App] failed to refresh chats after delete failure', err)
      }
    }
  }

  // Функция для очистки пустых локальных чатов
  const cleanupEmptyLocalChats = () => {
    setChats((prev) => {
      const cleaned = { ...prev }
      let hasChanges = false
      
      Object.keys(cleaned).forEach(chatId => {
        const chat = cleaned[chatId]
        // Удаляем пустые локальные чаты (не персистентные и без сообщений)
        // НО НЕ удаляем активный чат
        if (!chat.persisted && (!chat.messages || chat.messages.length === 0) && chatId !== activeChat) {
          delete cleaned[chatId]
          hasChanges = true
          console.log('[App] Cleaned up empty local chat:', chatId, '(not active)')
        }
      })
      
      return hasChanges ? cleaned : prev
    })
  }

  // Создание начального чата на сервере и установка как активного
  const createInitialChat = async () => {
    // Create a local (transient) chat. It will be persisted to the server only when the
    // first message is sent.
    const initialChatId = generateUUID()
    const initialChat = {
      id: initialChatId,
      server_id: null, // indicates not persisted yet
      title: "Чат с ассистентом",
      messages: [],
      createdAt: new Date(),
      persisted: false, // Local transient chat
    }
    setChats((prev) => ({ ...prev, [initialChatId]: initialChat }))
    // Note: caller should set activeChat if needed for initial login scenarios
    return initialChat
  }

  // Load chats from backend on mount
  useEffect(() => {
    let mounted = true
    // Try to restore auth session (so user stays logged in across reloads)
    const restoreSession = async () => {
      try {
        const sess = await getCurrentSession()
        console.log('[App] restoreSession session_exists=', !!sess)
        if (sess && sess.user && mounted) {
          setUser({ email: sess.user.email, name: sess.user.user_metadata?.name || sess.user.email })
        }
      } catch (e) {
        console.warn("[App] failed to restore session", e)
      } finally {
        if (mounted) setAuthLoaded(true)
      }
    }
  // Wait for session restore before loading chats (so Authorization header is present)
  // This function merges server chats into existing state without wiping local transient chats.
  // It will create the initial local chat only on the first successful load.
    const loadServerChatsAndEnsureInitial = async () => {
      console.log('[App] loadServerChatsAndEnsureInitial called')
      setLoadingChats(true)
      await restoreSession()
      if (!mounted) {
        setLoadingChats(false)
        return
      }
      // If there's no authenticated session after restore, avoid calling
      // server APIs (which will return 401) — instead create a local transient chat.
      try {
        const sess = await getCurrentSession()
        if (!sess || !sess.user) {
          console.debug('[App] no authenticated session, skipping server chat load')
          if (!initialLoadDoneRef.current) {
            const newChat = await createInitialChat()
            setActiveChat(newChat.id)
            initialLoadDoneRef.current = true
          }
          setLoadingChats(false)
          return
        }
      } catch (e) {
        console.warn('[App] error while checking session, proceeding to server load', e)
      }
      try {
        const serverChats = await getChats()
        console.log('[App] fetched serverChats (initial load):', serverChats)
        if (!mounted) return
        const mapped = {}
        for (const c of serverChats || []) {
          const previewRole = c.last_message_role || (c.last_message ? 'assistant' : null)
          const titleFromFirst = c.first_message ? (c.first_message.length > 60 ? c.first_message.slice(0, 60) + '...' : c.first_message) : null
          const defaultTitles = ['Новый чат', '', 'Чат с ассистентом']
          const useServerTitle = c.title && !defaultTitles.includes(c.title)
          mapped[c.id] = {
            id: c.id,
            server_id: c.id,
            title: useServerTitle ? c.title : (titleFromFirst || 'Новый чат'),
            messages: c.last_message ? [{ id: c.id + "-preview", role: previewRole, content: c.last_message, timestamp: c.created_at ? new Date(c.created_at) : new Date() }] : [],
            preview: Boolean(c.last_message),
            createdAt: c.created_at ? new Date(c.created_at) : new Date(),
            persisted: true, // Server chats are always persisted
          }
        }

        // Merge server chats into existing chats state. Do not remove local transient chats.
        setChats((prev) => {
          const copy = { ...prev }
          for (const k of Object.keys(mapped)) {
            copy[k] = mapped[k]
          }
          return copy
        })

        // Очищаем пустые локальные чаты после загрузки серверных (отложено)
        // setTimeout(() => cleanupEmptyLocalChats(), 100)

        // On the very first successful load, ensure there is at least one local chat selected
        console.log('[App] initialLoadDoneRef.current=', initialLoadDoneRef.current)
        if (!initialLoadDoneRef.current) {
          const hasAny = Object.keys(mapped).length > 0
          console.log('[App] initial load: hasAny=', hasAny, 'mapped=', mapped)
          if (!hasAny) {
            // No chats on server: create a local transient chat only. Do NOT
            // persist an empty chat to the server. The chat will be persisted
            // when the user sends the first message (ChatWindow handles that).
            console.log('[App] Creating initial chat for new user')
            const newChat = await createInitialChat()
            // Ensure the new chat is set as active
            setActiveChat(newChat.id)
            console.log('[App] Set active chat to:', newChat.id)
          } else {
            // If there are server chats, activate the first one
            const firstChatId = Object.keys(mapped)[0]
            if (firstChatId && !activeChat) {
              setActiveChat(firstChatId)
            }
            // Ensure a local initial chat exists alongside server chats if none present locally
            const hasLocal = Object.values(chats || {}).some((c) => !c.server_id)
            if (!hasLocal) {
              await createInitialChat()
            }
          }
          initialLoadDoneRef.current = true
        }
      } catch (e) {
        console.error("[App] failed to load chats:", e)
        // fallback to initial chat on first load only
        if (!initialLoadDoneRef.current) {
          const newChat = await createInitialChat()
          setActiveChat(newChat.id)
          initialLoadDoneRef.current = true
        }
      }
      setLoadingChats(false)
    }

    // Start loading immediately
    loadServerChatsAndEnsureInitial().catch((e) => console.error('[App] initial load failed', e))
    
    // Subscribe to auth changes to keep UI in sync
    const { data: listener } = supabase.auth.onAuthStateChange((event, session) => {
      console.debug("[App] auth state changed", event)
      if (event === "SIGNED_IN" && session?.user) {
        setUser({ email: session.user.email, name: session.user.user_metadata?.name || session.user.email })
        setAuthLoaded(true)
        // Ensure we fetch server chats immediately after sign-in
        if (!initialLoadDoneRef.current) {
          loadServerChatsAndEnsureInitial().catch((e) => console.warn('[App] load after SIGNED_IN failed', e))
        }
      }
      if (event === "SIGNED_OUT") {
        // On sign-out, clear UI state and reset initial-load so a future
        // sign-in will re-run the server chat creation flow.
        try {
          initialLoadDoneRef.current = false
        } catch (e) {}
        setUser(null)
        setChats({})
        setActiveChat(null)
        setAuthLoaded(true)
      }
    })
    return () => {
      mounted = false
      try {
        listener.subscription.unsubscribe()
      } catch (e) {}
    }
  }, [])

  // Helper to transform raw messages from API into frontend message objects
  const transformMessages = (msgs) =>
    msgs.map((m) => ({
      id: m.id,
      chat_id: m.chat_id,
      role: m.role,
      content: m.content,
      files: m.files || [],
      tables: m.tables || [],
      charts: m.charts || [],
      timestamp: m.created_at ? new Date(m.created_at) : new Date(),
      createdAt: m.created_at ? new Date(m.created_at) : new Date(),
      owner_id: m.owner_id || null,
    }))

  // Handle selecting a chat: prefetch messages for server-backed chats before
  // switching activeChat to avoid showing only the preview then later the rest.
  const handleSelectChat = async (chatId) => {
    // Очищаем пустые локальные чаты при переключении
    cleanupEmptyLocalChats()
    
    const chatObj = chats[chatId]
    // If this is a local transient chat with no server_id and not a preview, just activate it
    if (chatObj && !chatObj.server_id && !chatObj.preview) {
      setActiveChat(chatId)
      return
    }

    // Otherwise, prefetch full messages (use server_id when available)
    try {
      setLoadingChatId(chatId)
      const targetId = chatObj && chatObj.server_id ? chatObj.server_id : chatId
      const msgs = await getChatMessages(targetId)
      const transformed = transformMessages(msgs)
      // Update the chat messages and clear preview flag before activating
      updateChatMessages(chatId, transformed, { preview: false })
      setActiveChat(chatId)
    } catch (e) {
      console.error('[App] failed to prefetch messages for chat', chatId, e)
      // Fallback: still activate the chat so user can interact
      setActiveChat(chatId)
    } finally {
      setLoadingChatId(null)
    }
  }

  // When activeChat changes, load messages for it (if not already loaded)
  useEffect(() => {
    let mounted = true
    const loadMessages = async (chatId) => {
      try {
        const chatObj = chats[chatId]
        // If this is a local transient chat (not yet persisted on server) and
        // it's not a preview of a server chat, skip fetching messages from the API.
        // The app persists this chat only when the first message is sent, so
        // requesting messages for a non-persisted id will return 404.
        if (chatObj && !chatObj.preview && !chatObj.server_id) {
          console.debug('[App] skipping server fetch for transient local chat', chatId)
          return
        }
        // If this chat was loaded as a preview only, always fetch full messages
        if (chatObj && chatObj.preview) {
          const msgs = await getChatMessages(chatId)
          if (!mounted) return
          const transformed = msgs.map((m) => ({
            id: m.id,
            chat_id: m.chat_id,
            role: m.role,
            content: m.content,
            files: m.files || [],
            tables: m.tables || [],
            charts: m.charts || [],
            timestamp: m.created_at ? new Date(m.created_at) : new Date(),
            createdAt: m.created_at ? new Date(m.created_at) : new Date(),
            owner_id: m.owner_id || null,
          }))
          console.log("[App] loaded messages for chat", chatId, "count", transformed.length)
          // replace messages and clear preview flag
          updateChatMessages(chatId, transformed, { preview: false })
          return
        }
  // Use server_id when available (server-persisted chat), otherwise fall back
  // to the chatId (useful for legacy/server-originated ids).
  const targetId = chatObj && chatObj.server_id ? chatObj.server_id : chatId
  const msgs = await getChatMessages(targetId)
        if (!mounted) return
        if (msgs && msgs.length > 0) {
          const transformed = msgs.map((m) => ({
            id: m.id,
            chat_id: m.chat_id,
            role: m.role,
            content: m.content,
            files: m.files || [],
            tables: m.tables || [],
            charts: m.charts || [],
            // frontend Message component expects `timestamp` property (used for toLocaleTimeString())
            timestamp: m.created_at ? new Date(m.created_at) : new Date(),
            // also keep createdAt for other parts of the UI if needed
            createdAt: m.created_at ? new Date(m.created_at) : new Date(),
            owner_id: m.owner_id || null,
          }))
          console.log("[App] loaded messages for chat", chatId, "count", transformed.length)
          updateChatMessages(chatId, transformed)
        }
      } catch (e) {
        console.error("[App] failed to load messages for chat", chatId, e)
      }
    }

    if (activeChat) {
      const chatObj = chats[activeChat]
      // If chat exists and has no messages loaded, or it's a preview-only chat, fetch full messages
      if (chatObj && (chatObj.preview || !chatObj.messages || chatObj.messages.length === 0)) {
        loadMessages(activeChat)
      }
    }

    return () => {
      mounted = false
    }
  }, [activeChat])

  // Автоматически выбираем первый доступный чат, если нет активного
  useEffect(() => {
    console.log('[App] Auto-select effect: activeChat=', activeChat, 'chats.length=', Object.keys(chats).length, 'user=', !!user)
    if (!activeChat && Object.keys(chats).length > 0 && user) {
      // Находим первый чат, который не является пустым локальным чатом
      const availableChats = Object.values(chats).filter(chat => {
        // Включаем персистентные чаты и локальные чаты с сообщениями
        return chat.persisted || (chat.messages && chat.messages.length > 0)
      })
      
      if (availableChats.length > 0) {
        const firstChatId = availableChats[0].id
        console.log('[App] Auto-selecting first available chat:', firstChatId)
        setActiveChat(firstChatId)
      } else {
        // Если нет подходящих чатов, выбираем любой первый (может быть пустой локальный)
        const firstChatId = Object.keys(chats)[0]
        console.log('[App] Auto-selecting first chat (even if empty):', firstChatId)
        setActiveChat(firstChatId)
      }
    }
  }, [chats, activeChat, user])

  // Создание нового чата (локального, будет сохранен на сервере при отправке первого сообщения)
  const createNewChat = async () => {
    const newChatId = generateUUID()
    const newChat = {
      id: newChatId,
      server_id: null, // indicates not persisted yet
      title: "Новый чат",
      messages: [],
      createdAt: new Date(),
      persisted: false, // Local transient chat
    }
    setChats((prev) => ({ ...prev, [newChatId]: newChat }))
    setActiveChat(newChatId)
    return newChat
  }

  // Обновление сообщений чата
  const updateChatMessages = (chatId, messages, metadata = {}) => {
    console.log("[App] updateChatMessages called for", chatId, "messages count", messages.length, "metadata", metadata)
    setChats((prev) => ({
      ...prev,
      [chatId]: {
        ...prev[chatId],
        ...metadata,
        messages,
        // Обновляем название чата на основе первого сообщения пользователя
        // Только для локальных/транзиентных чатов (server_id === null).
        // Для серверных чатов (server_id present) сохраняем заголовок, чтобы
        // плитка чата не меняла описание при подгрузке сообщений.
        title: (() => {
          const existing = prev[chatId] || {}
          const isTransient = !existing.server_id
          if (isTransient && messages.length > 0 && messages[0].role === "user") {
            return messages[0].content.slice(0, 30) + (messages[0].content.length > 30 ? "..." : "")
          }
          return existing.title
        })(),
      },
    }))
  }

  // Если пользователь не авторизован, показываем страницы входа/регистрации
  // Avoid flashing the login form while we attempt to restore session
  if (!authLoaded) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-gray-500">Загрузка...</div>
      </div>
    )
  }

  if (!user) {
    if (authPage === "login") {
      return <LoginPage onLogin={handleLogin} onSwitchToRegister={() => setAuthPage("register")} />
    } else {
      return <RegisterPage onRegister={handleRegister} onSwitchToLogin={() => setAuthPage("login")} />
    }
  }

  // Основной интерфейс чата для авторизованных пользователей
  const currentChat = activeChat ? chats[activeChat] : null

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar
        chats={chats}
        activeChat={activeChat}
        onChatSelect={handleSelectChat}
        onNewChat={createNewChat}
        onDelete={handleDeleteChat}
        user={user}
        onLogout={handleLogout}
        loading={loadingChats}
      />
      <ChatWindow chat={currentChat} onUpdateMessages={updateChatMessages} />
    </div>
  )
}

export default App
