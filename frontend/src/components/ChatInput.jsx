import { useState, useRef, useEffect } from 'react'

function ChatInput({ onSendMessage, centered = false, isLoading = false, persistentFiles = [], onClearFiles }) {
  const [message, setMessage] = useState('')
  const [files, setFiles] = useState([])
  const fileInputRef = useRef(null)

  // Синхронизируем локальные файлы с persistent файлами
  useEffect(() => {
    if (persistentFiles.length > 0) {
      setFiles(persistentFiles)
    }
  }, [persistentFiles])

  const handleSubmit = (e) => {
    e.preventDefault()
    
    const trimmedMessage = message.trim()
    
    // Проверяем, что есть либо текст, либо файлы
    if ((trimmedMessage || files.length > 0) && !isLoading) {
      // Если нет текста, но есть файлы, добавляем сообщение по умолчанию
      const messageToSend = trimmedMessage || (files.length > 0 ? `Отправлено файлов: ${files.length}` : '')
      
      if (messageToSend) {
        onSendMessage(messageToSend, files)
        setMessage('')
        // Файлы остаются - не очищаем их здесь
      }
    }
  }

  const handleFileSelect = (e) => {
    const selectedFiles = Array.from(e.target.files)
    setFiles(prev => [...prev, ...selectedFiles])
  }

  const removeFile = (index) => {
    setFiles(prev => prev.filter((_, i) => i !== index))
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <div className={centered ? "bg-transparent" : "border-t border-gray-200 bg-white"}>
      <div className="max-w-3xl mx-auto p-4">
        {/* Прикрепленные файлы */}
        {files.length > 0 && (
          <div className="mb-3">
            {/* Заголовок с кнопкой очистки */}
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-gray-600">
                Прикреплено файлов: {files.length}
              </span>
              <button
                onClick={() => {
                  setFiles([])
                  if (onClearFiles) {
                    onClearFiles()
                  }
                }}
                disabled={isLoading}
                className="text-xs text-red-500 hover:text-red-700 disabled:text-gray-400"
              >
                Очистить все
              </button>
            </div>
            
            {/* Список файлов */}
            <div className="flex flex-wrap gap-2">
              {files.map((file, index) => (
                <div key={index} className="flex items-center gap-2 bg-gray-100 px-3 py-1 rounded-full text-sm">
                  <svg 
                    width="14" 
                    height="14" 
                    viewBox="0 0 24 24" 
                    fill="none" 
                    stroke="currentColor" 
                    strokeWidth="2" 
                    strokeLinecap="round" 
                    strokeLinejoin="round"
                    className="text-gray-600"
                  >
                    <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
                  </svg>
                  <span className="truncate max-w-32">{file.name}</span>
                  <button
                    onClick={() => removeFile(index)}
                    disabled={isLoading}
                    className="text-gray-500 hover:text-red-500 ml-1 disabled:text-gray-400"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Форма ввода */}
        <form onSubmit={handleSubmit} className="relative">
          <div className={`flex items-center gap-2 rounded-lg overflow-hidden transition-all ${
            centered 
              ? "border-2 border-gray-300 focus-within:border-blue-500 focus-within:shadow-lg" 
              : "border border-gray-300 focus-within:border-blue-500"
          }`}>
            {/* Кнопка прикрепления файлов */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isLoading}
              className={`p-3 transition-colors group flex-shrink-0 ${
                isLoading 
                  ? 'text-gray-300 cursor-not-allowed' 
                  : 'text-gray-500 hover:text-blue-500'
              }`}
              title={isLoading ? "Ожидание ответа..." : "Прикрепить файл"}
            >
              <svg 
                width="18" 
                height="18" 
                viewBox="0 0 24 24" 
                fill="none" 
                stroke="currentColor" 
                strokeWidth="2" 
                strokeLinecap="round" 
                strokeLinejoin="round"
                className="group-hover:rotate-12 transition-transform"
              >
                <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
              </svg>
            </button>

            {/* Поле ввода */}
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                isLoading 
                  ? "Ожидание ответа..." 
                  : files.length > 0
                    ? "Добавьте описание к файлам (необязательно)..."
                    : centered 
                      ? "Задайте ваш вопрос..." 
                      : "Напишите сообщение..."
              }
              disabled={isLoading}
              className={`flex-1 resize-none border-0 outline-none max-h-32 min-h-[24px] ${
                centered ? "py-4 text-base" : "py-3"
              } ${isLoading ? "bg-gray-50 text-gray-400 cursor-not-allowed" : ""}`}
              rows="1"
            />

            {/* Кнопка отправки */}
            <button
              type="submit"
              disabled={(!message.trim() && files.length === 0) || isLoading}
              className={`p-3 transition-colors group flex-shrink-0 ${
                ((!message.trim() && files.length === 0) || isLoading)
                  ? 'text-gray-300 cursor-not-allowed'
                  : 'text-blue-500 hover:text-blue-600'
              }`}
              title={isLoading ? "Ожидание ответа..." : "Отправить сообщение"}
            >
              {isLoading ? (
                <svg 
                  width="18" 
                  height="18" 
                  viewBox="0 0 24 24" 
                  fill="none" 
                  stroke="currentColor" 
                  strokeWidth="2" 
                  className="animate-spin"
                >
                  <path d="M21 12a9 9 0 11-6.219-8.56"/>
                </svg>
              ) : (
                <svg 
                  width="18" 
                  height="18" 
                  viewBox="0 0 24 24" 
                  fill="none" 
                  stroke="currentColor" 
                  strokeWidth="2" 
                  strokeLinecap="round" 
                  strokeLinejoin="round"
                  className="group-hover:translate-x-1 transition-transform"
                >
                  <path d="m3 3 3 9-3 9 19-9Z"/>
                  <path d="m6 12 15 0"/>
                </svg>
              )}
            </button>
          </div>

          {/* Скрытое поле для выбора файлов */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={handleFileSelect}
            disabled={isLoading}
            className="hidden"
          />
        </form>

        {/* Подсказка */}
        {!centered && (
          <div className="text-xs text-gray-400 mt-2 text-center">
            Нажмите Enter для отправки, Shift+Enter для новой строки
          </div>
        )}
      </div>
    </div>
  )
}

export default ChatInput
