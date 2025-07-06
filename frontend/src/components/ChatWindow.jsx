import { useState } from 'react'
import MessageList from './MessageList'
import ChatInput from './ChatInput'

// Генерация UUID v4
function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0
    const v = c == 'x' ? r : (r & 0x3 | 0x8)
    return v.toString(16)
  })
}

function ChatWindow({ chat, onUpdateMessages }) {
  const [isLoading, setIsLoading] = useState(false)

  if (!chat) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-gray-500">Выберите чат или создайте новый</div>
      </div>
    )
  }

  const handleSendMessage = (content, files) => {
    if (isLoading) return // Блокируем отправку если уже загружается
    
    setIsLoading(true) // Устанавливаем состояние загрузки
    
    // Создаем сообщение пользователя
    const userMessage = {
      id: generateUUID(),
      role: 'user',
      content,
      files,
      timestamp: new Date()
    }
    
    const updatedMessages = [...chat.messages, userMessage]
    onUpdateMessages(chat.id, updatedMessages)

    // Симуляция ответа ассистента
    setTimeout(() => {
      const assistantMessage = {
        id: generateUUID(),
        role: 'assistant',
        content: 'Спасибо за ваше сообщение! Это демонстрационный ответ ассистента.',
        timestamp: new Date()
      }
      
      onUpdateMessages(chat.id, [...updatedMessages, assistantMessage])
      setIsLoading(false) // Сбрасываем состояние загрузки
    }, 1000)
  }

  // Проверяем, есть ли сообщения в чате
  const isEmpty = chat.messages.length === 0

  if (isEmpty) {
    // Пустой чат - форма по центру с приветствием
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8">
        <div className="max-w-2xl w-full text-center mb-8">
          <h1 className="text-3xl font-semibold text-gray-800 mb-4">
            Чем я могу вам помочь?
          </h1>
          <p className="text-gray-600 mb-8">
            Задайте любой вопрос или начните новый разговор
          </p>
        </div>
        <div className="w-full max-w-3xl">
          <ChatInput onSendMessage={handleSendMessage} centered={true} isLoading={isLoading} />
        </div>
      </div>
    )
  }

  // Чат с сообщениями - обычная компоновка
  return (
    <div className="flex-1 flex flex-col">
      <MessageList messages={chat.messages} />
      <ChatInput onSendMessage={handleSendMessage} centered={false} isLoading={isLoading} />
    </div>
  )
}

export default ChatWindow
