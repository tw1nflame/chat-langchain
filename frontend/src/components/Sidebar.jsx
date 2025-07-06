function Sidebar({ chats, activeChat, onChatSelect, onNewChat }) {
  // Сортируем чаты по времени создания (новые сверху)
  const sortedChats = Object.values(chats).sort((a, b) => 
    new Date(b.createdAt) - new Date(a.createdAt)
  )

  const getLastMessage = (messages) => {
    if (messages.length === 0) return 'Пустой чат'
    const lastMessage = messages[messages.length - 1]
    return lastMessage.content.slice(0, 40) + (lastMessage.content.length > 40 ? '...' : '')
  }

  return (
    <div className="w-64 bg-gray-900 text-white flex flex-col">
      {/* Кнопка нового чата */}
      <div className="p-3 border-b border-gray-700">
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
        {sortedChats.map((chat) => (
          <div
            key={chat.id}
            onClick={() => onChatSelect(chat.id)}
            className={`p-3 cursor-pointer hover:bg-gray-800 transition-colors border-l-2 ${
              activeChat === chat.id 
                ? 'bg-gray-800 border-blue-500' 
                : 'border-transparent'
            }`}
          >
            <div className="text-sm font-medium truncate">{chat.title}</div>
            <div className="text-xs text-gray-400 truncate mt-1">
              {getLastMessage(chat.messages)}
            </div>
          </div>
        ))}
      </div>

      {/* Нижняя панель */}
      <div className="p-3 border-t border-gray-700">
        <div className="text-xs text-gray-400">
          Чат-ассистент
        </div>
      </div>
    </div>
  )
}

export default Sidebar
