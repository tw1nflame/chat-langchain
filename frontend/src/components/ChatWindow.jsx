"use client"

import { useState } from "react"
import MessageList from "./MessageList"
import ChatInput from "./ChatInput"
import { sendMessage, createChat, confirmPlan } from "../api/chat"

// Генерация UUID v4
function generateUUID() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c == "x" ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

function ChatWindow({ chat, onUpdateMessages }) {
  const [isLoading, setIsLoading] = useState(false)
  const [persistentFiles, setPersistentFiles] = useState([])

  // Debug: log chat render info
  try {
    // eslint-disable-next-line no-console
    console.debug("[ChatWindow] render chat id:", chat?.id, "messages length:", chat?.messages?.length)
  } catch (e) {}

  if (!chat) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-gray-500">Выберите чат или создайте новый</div>
      </div>
    )
  }

  const handleSendMessage = async (content, files) => {
    if (isLoading) return // Блокируем отправку если уже загружается

    // Сразу добавляем сообщение пользователя
    const userMessage = {
      id: generateUUID(),
      role: "user",
      content: content,
      files:
        files.map((file) => ({
          name: file.name,
          size: file.size,
          type: file.type,
        })) || [],
      timestamp: new Date(),
    }

    // Обновляем состояние с сообщением пользователя
    const messagesWithUser = [...chat.messages, userMessage]
    onUpdateMessages(chat.id, messagesWithUser)

    setIsLoading(true) // Устанавливаем состояние загрузки

    try {
      console.log("[ChatWindow] Sending message: chatId=", chat.id, "content=", content, "files=", files)
      
      // Check if the chat still exists (basic sanity check)
      if (!chat || !chat.id) {
        console.log("[ChatWindow] Chat no longer exists, canceling message send")
        return
      }
      
      // Step 1: Ensure chat exists on server
      let serverId = chat.server_id || null
      if (!serverId) {
        console.log("[ChatWindow] Creating chat on server first...")
        const serverChat = await createChat(chat.title || "Новый чат")
        serverId = serverChat.id
        
        // Update local chat to remember server id and preserve the freshly added user message
        // IMPORTANT: Also update the server_id immediately to avoid race conditions
        onUpdateMessages(chat.id, messagesWithUser, { 
          server_id: serverId,
          // Ensure the chat is marked as persisted
          persisted: true 
        })
        console.log("[ChatWindow] Chat created on server with ID:", serverId)
      }

      // Step 2: Send message to existing chat
      console.log("[ChatWindow] Sending message to chat:", serverId)
      const response = await sendMessage(serverId, content, files)
  console.log("[ChatWindow] sendMessage response:", response)

      // Создаем сообщение ассистента
      const assistantMessage = {
        id: response.assistantMessage.id,
        role: response.assistantMessage.role,
        content: response.assistantMessage.content,
        files: response.assistantMessage.files || [],
        tables: response.assistantMessage.tables || [],
        charts: response.assistantMessage.charts || [],
        timestamp: new Date(response.assistantMessage.created_at),
        awaiting_confirmation: response.assistantMessage.awaiting_confirmation || false,
        confirmation_summary: response.assistantMessage.confirmation_summary || null,
        plan_id: response.assistantMessage.plan_id || null,
      }

      // Добавляем сообщение ассистента к уже существующим сообщениям
      const finalMessages = [...messagesWithUser, assistantMessage]
      onUpdateMessages(chat.id, finalMessages)
    } catch (error) {
      // Check if the error is because chat was deleted during processing
      if (error.message && (error.message.includes('ChatDeletedError') || 
          error.message.includes('Chat was deleted') || 
          error.message.includes('404'))) {
        console.log("[ChatWindow] Chat was deleted during processing, not showing error message")
        return
      }

      // Only log error if it's not a "chat deleted" case
      console.error("[ChatWindow] Ошибка при отправке сообщения:", error)

      // В случае ошибки добавляем сообщение об ошибке
      const errorMessage = {
        id: generateUUID(),
        role: "assistant",
        content: "Извините, произошла ошибка при отправке сообщения. Попробуйте еще раз.",
        files: [],
        timestamp: new Date(),
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
          <h1 className="text-4xl font-semibold text-gray-800 mb-4">Чем вам помочь?</h1>
          <p className="text-lg text-gray-600 mb-8">Задайте любой вопрос, загрузите файлы или начните новый разговор</p>
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

  // Confirm plan handler
  const handleConfirmPlan = async (messageId, confirm) => {
    // Must have a persisted server id for confirmation
    const serverId = chat.server_id
    if (!serverId) {
      alert('Нельзя подтвердить план: чат не сохранён на сервере yet.')
      return
    }

    // Find message and extract planId
    const msg = chat.messages.find(m => m.id === messageId)
    const planId = msg?.plan_id || null
    if (!planId) {
      alert('Невозможно подтвердить: отсутствует plan_id для сообщения. Попробуйте обновить страницу.')
      return
    }

    try {
      const resp = await confirmPlan(serverId, confirm, planId)

      // Update the assistant message in UI
      const updated = chat.messages.map((m) => {
        if (m.id !== messageId) return m
        // Copy and update
        const nm = { ...m }
        if (confirm) {
          nm.content = resp.content || nm.content
          nm.tables = resp.tables || nm.tables || []
          nm.charts = resp.charts || nm.charts || []
          nm.awaiting_confirmation = false
          nm.confirmation_summary = null
          nm.plan_id = null
        } else {
          nm.content = resp.result || 'План отменён.'
          nm.awaiting_confirmation = false
          nm.confirmation_summary = null
          nm.plan_id = null
        }
        return nm
      })

      onUpdateMessages(chat.id, updated)
    } catch (e) {
      console.error('Confirm plan failed', e)
      alert('Ошибка при подтверждении плана: ' + (e.message || e))
    }
  }

  // Чат с сообщениями - обычная компоновка
  return (
    <div className="flex-1 flex flex-col">
      <MessageList messages={chat.messages} chatId={chat.id} onConfirm={handleConfirmPlan} />
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
