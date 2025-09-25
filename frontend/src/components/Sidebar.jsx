"use client"

function Sidebar({ chats, activeChat, onChatSelect, onNewChat, user, onLogout, onDelete, loading = false }) {
  // Сортируем чаты по времени создания (новые сверху)
  const sortedChats = Object.values(chats).sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))

  // Debug: log each chat summary
  try {
    // eslint-disable-next-line no-console
    console.debug("[Sidebar] chats summary", sortedChats.map((c) => ({ id: c.id, title: c.title, messagesLen: (c.messages || []).length })))
  } catch (e) {}

  const getLastMessage = (messages) => {
    if (!messages || messages.length === 0) return "Пустой чат"
    const lastMessage = messages[messages.length - 1]
    const content = lastMessage?.content || ""
    return content.slice(0, 40) + (content.length > 40 ? "..." : "")
  }

  return (
    <div className="w-64 bg-gray-900 text-white flex flex-col overflow-x-hidden">
      {/* Информация о пользователе */}
      <div className="p-3 border-b border-gray-700">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-blue-500 rounded-full flex items-center justify-center text-sm font-medium">
              {user?.name?.charAt(0)?.toUpperCase() || "U"}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium truncate">{user?.name || "Пользователь"}</div>
              <div className="text-xs text-gray-400 truncate">{user?.email}</div>
            </div>
          </div>
          <button
            onClick={onLogout}
            className="text-gray-400 hover:text-red-400 transition-colors p-1"
            title="Выйти из аккаунта"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16,17 21,12 16,7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
          </button>
        </div>

        {/* Кнопка нового чата */}
        <button
          onClick={onNewChat}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg border border-gray-600 hover:bg-gray-800 transition-colors"
        >
          <span className="text-lg">+</span>
          <span className="text-sm">Новый чат</span>
        </button>
      </div>

      {/* Список чатов */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          // Simple loading skeleton: three rows
          <div className="p-3">
            <div className="space-y-2">
              <div className="h-4 bg-gray-700 rounded w-3/4 animate-pulse" />
              <div className="h-4 bg-gray-700 rounded w-2/3 animate-pulse" />
              <div className="h-4 bg-gray-700 rounded w-1/2 animate-pulse" />
            </div>
          </div>
        ) : sortedChats.length === 0 ? (
          <div className="p-3 text-center text-gray-400 text-sm">Нет чатов</div>
        ) : (
          sortedChats.map((chat) => (
            <div
              key={chat.id}
              className={`p-3 flex items-center justify-between cursor-pointer hover:bg-gray-800 transition-colors border-l-2 ${
                activeChat === chat.id ? "bg-gray-800 border-blue-500" : "border-transparent"
              }`}
            >
              <div className="flex-1 min-w-0" onClick={() => onChatSelect(chat.id)}>
                <div className="text-sm font-medium truncate">{chat.title}</div>
                <div className="text-xs text-gray-400 truncate mt-1">{getLastMessage(chat.messages)}</div>
              </div>
              <div className="ml-3 flex-shrink-0">
                {!( !chat.server_id && (!chat.messages || chat.messages.length === 0) ) ? (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      if (typeof onDelete === 'function') onDelete(chat.id)
                    }}
                    className="text-gray-400 hover:text-red-400 p-1"
                    title="Удалить чат"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                      <path d="M10 11v6" />
                      <path d="M14 11v6" />
                    </svg>
                  </button>
                ) : (
                  <div className="w-6 h-6" aria-hidden />
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Нижняя панель */}
      <div className="p-3 border-t border-gray-700">
        <div className="text-xs text-gray-400">Чат-ассистент v2.0</div>
      </div>
    </div>
  )
}

export default Sidebar
