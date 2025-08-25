import { useState } from 'react'
import MessageList from './MessageList'
import ChatInput from './ChatInput'
import { sendMessage } from '../api/chat'

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
  const [persistentFiles, setPersistentFiles] = useState([])

  if (!chat) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-gray-500">Выберите чат или создайте новый</div>
      </div>
    )
  }

  const handleSendMessage = async (content, files) => {
    if (isLoading) return // Блокируем отправку если уже загружается
    
    // Сохраняем файлы для следующего сообщения если они были отправлены
    if (files && files.length > 0) {
      setPersistentFiles(files)
    }
    
    // Сразу добавляем сообщение пользователя
    const userMessage = {
      id: generateUUID(),
      role: 'user',
      content: content,
      files: files.map(file => ({
        name: file.name,
        size: file.size,
        type: file.type
      })) || [],
      timestamp: new Date()
    }
    
    // Обновляем состояние с сообщением пользователя
    const messagesWithUser = [...chat.messages, userMessage]
    onUpdateMessages(chat.id, messagesWithUser)
    
    setIsLoading(true) // Устанавливаем состояние загрузки
    
    try {
      // Отправляем сообщение пользователя и получаем оба сообщения
      const response = await sendMessage(chat.id, content, files)
      
      // Создаем сообщение ассистента
      const assistantMessage = {
        id: response.assistantMessage.id,
        role: response.assistantMessage.role,
        content: response.assistantMessage.content,
        files: response.assistantMessage.files || [],
        timestamp: new Date(response.assistantMessage.created_at)
      }
      
      // Добавляем сообщение ассистента к уже существующим сообщениям
      const finalMessages = [...messagesWithUser, assistantMessage]
      onUpdateMessages(chat.id, finalMessages)
    } catch (error) {
      console.error('Ошибка при отправке сообщения:', error)
      
      // В случае ошибки добавляем сообщение об ошибке
      const errorMessage = {
        id: generateUUID(),
        role: 'assistant',
        content: 'Извините, произошла ошибка при отправке сообщения. Попробуйте еще раз.',
        files: [],
        timestamp: new Date()
      }
      
      const errorMessages = [...messagesWithUser, errorMessage]
      onUpdateMessages(chat.id, errorMessages)
    } finally {
      setIsLoading(false) // Сбрасываем состояние загрузки
    }
  }

  const handleClearFiles = () => {
    setPersistentFiles([])
  }

  // Проверяем, есть ли сообщения в чате
  const isEmpty = chat.messages.length === 0

  if (isEmpty) {
    // Пустой чат - форма по центру с приветствием
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 bg-white">
        <div className="max-w-2xl w-full text-center mb-8">
          <h1 className="text-4xl font-semibold text-gray-800 mb-4">
            Чем вам помочь?
          </h1>
          <p className="text-lg text-gray-600 mb-8">
            Задайте любой вопрос, загрузите файлы или начните новый разговор
          </p>
        </div>
        <div className="w-full max-w-4xl">
          <ChatInput 
            onSendMessage={handleSendMessage} 
            centered={true} 
            isLoading={isLoading} 
            persistentFiles={persistentFiles}
            onClearFiles={handleClearFiles}
          />
        </div>
      </div>
    )
  }

  // Чат с сообщениями - обычная компоновка
  return (
    <div className="flex-1 flex flex-col">
      <MessageList messages={chat.messages} />
      <ChatInput 
        onSendMessage={handleSendMessage} 
        centered={false} 
        isLoading={isLoading} 
        persistentFiles={persistentFiles}
        onClearFiles={handleClearFiles}
      />
    </div>
  )
}

export default ChatWindow
