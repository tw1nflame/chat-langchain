const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

// Отправить сообщение в чат и получить ответ ассистента
export const sendMessage = async (chatId, content, files = []) => {
  const formData = new FormData()
  formData.append('role', 'user')
  formData.append('content', content)
  
  // Добавляем файлы в FormData (если есть)
  if (files && files.length > 0) {
    files.forEach((file) => {
      formData.append('files', file)
    })
  }
  
  const response = await fetch(`${API_BASE}/api/v1/chats/${chatId}/messages`, {
    method: 'POST',
    body: formData
  })
  
  if (!response.ok) {
    const errorText = await response.text()
    console.error('Server error:', errorText)
    throw new Error(`HTTP error! status: ${response.status}`)
  }
  
  const result = await response.json()
  
  // Возвращаем оба сообщения из нового API
  return {
    userMessage: result.user_message,
    assistantMessage: result.assistant_message
  }
}

// Получить все сообщения чата
export const getChatMessages = async (chatId) => {
  const response = await fetch(`${API_BASE}/api/v1/chats/${chatId}/messages`)
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

// Создать новый чат
export const createChat = async (title = null) => {
  const response = await fetch(`${API_BASE}/api/v1/chats`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ title })
  })
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

// Получить все чаты
export const getChats = async () => {
  const response = await fetch(`${API_BASE}/api/v1/chats`)
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}
