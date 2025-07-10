import { useState } from 'react'
// import Sidebar from './components/Sidebar' // Временно закомментировано
import ChatWindow from './components/ChatWindow'

// Генерация UUID v4
function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0
    const v = c == 'x' ? r : (r & 0x3 | 0x8)
    return v.toString(16)
  })
}

function App() {
  // Создаем один единственный чат без предварительных сообщений
  const [chats, setChats] = useState(() => {
    const initialChats = {}
    const defaultChatId = generateUUID()
    
    initialChats[defaultChatId] = {
      id: defaultChatId,
      title: 'Чат с ассистентом',
      messages: [], // Пустой массив сообщений для отображения приветственной формы
      createdAt: new Date()
    }
    
    // Закомментированные дополнительные чаты
    /*
    const chatId2 = generateUUID()
    
    initialChats[chatId2] = {
      id: chatId2,
      title: 'Вопросы по разработке',
      messages: [
        {
          id: generateUUID(),
          role: 'user',
          content: 'Объясни как работают React хуки',
          timestamp: new Date(Date.now() - 60000)
        },
        {
          id: generateUUID(),
          role: 'assistant',
          content: 'React хуки - это функции, которые позволяют использовать состояние и другие возможности React в функциональных компонентах.',
          timestamp: new Date(Date.now() - 30000)
        }
      ],
      createdAt: new Date(Date.now() - 120000)
    }
    */
    
    return initialChats
  })
  
  const [activeChat, setActiveChat] = useState(() => Object.keys(chats)[0])

  // Закомментированные функции для работы с несколькими чатами
  /*
  const createNewChat = () => {
    const newChatId = generateUUID()
    const newChat = {
      id: newChatId,
      title: 'Новый чат',
      messages: [],
      createdAt: new Date()
    }
    
    setChats(prev => ({ ...prev, [newChatId]: newChat }))
    setActiveChat(newChatId)
  }
  */

  const updateChatMessages = (chatId, messages) => {
    setChats(prev => ({
      ...prev,
      [chatId]: {
        ...prev[chatId],
        messages,
        // Обновляем название чата на основе первого сообщения пользователя
        title: messages.length > 0 && messages[0].role === 'user' 
          ? messages[0].content.slice(0, 30) + (messages[0].content.length > 30 ? '...' : '')
          : prev[chatId].title
      }
    }))
  }

  const currentChat = chats[activeChat]

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Временно закомментирован сайдбар */}
      {/*
      <Sidebar 
        chats={chats}
        activeChat={activeChat}
        onChatSelect={setActiveChat}
        onNewChat={createNewChat}
      />
      */}
      <ChatWindow 
        chat={currentChat}
        onUpdateMessages={updateChatMessages}
      />
    </div>
  )
}

export default App
