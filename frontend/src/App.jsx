import { useState } from 'react'
import Sidebar from './components/Sidebar'
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
  // Структура чатов с UUID и сообщениями в формате ChatGPT
  const [chats, setChats] = useState(() => {
    const initialChats = {}
    const chatId1 = generateUUID()
    const chatId2 = generateUUID()
    
    initialChats[chatId1] = {
      id: chatId1,
      title: 'Общение с ассистентом',
      messages: [
        {
          id: generateUUID(),
          role: 'assistant',
          content: 'Привет! Я готов помочь вам с любыми вопросами.',
          timestamp: new Date()
        }
      ],
      createdAt: new Date()
    }
    
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
    
    return initialChats
  })
  
  const [activeChat, setActiveChat] = useState(() => Object.keys(chats)[0])

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
      <Sidebar 
        chats={chats}
        activeChat={activeChat}
        onChatSelect={setActiveChat}
        onNewChat={createNewChat}
      />
      <ChatWindow 
        chat={currentChat}
        onUpdateMessages={updateChatMessages}
      />
    </div>
  )
}

export default App
