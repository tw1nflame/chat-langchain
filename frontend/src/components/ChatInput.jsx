"use client"

import { useState, useRef, useEffect } from "react"

function ChatInput({ onSendMessage, centered = false, isLoading = false, isAwaitingConfirmation = false, persistentFiles = [], onClearFiles, value, onChange }) {
  const [internalMessage, setInternalMessage] = useState("")
  const [files, setFiles] = useState([])
  const fileInputRef = useRef(null)
  const textareaRef = useRef(null)
  
  const isControlled = value !== undefined
  const message = isControlled ? value : internalMessage

  // Синхронизируем локальные файлы с persistent файлами
  useEffect(() => {
    if (persistentFiles.length > 0) {
      setFiles(persistentFiles)
    }
  }, [persistentFiles])

  // Автоматическое изменение размера textarea
  const adjustTextareaHeight = () => {
    const textarea = textareaRef.current
    if (textarea) {
      // Сбрасываем высоту к минимальной для корректного расчета scrollHeight
      textarea.style.height = 'auto'
      
      // Устанавливаем ограничения
      const maxHeight = 200 // максимальная высота (примерно 8-9 строк)
      const scrollHeight = textarea.scrollHeight
      
      // Применяем высоту с учетом ограничений
      const newHeight = Math.min(maxHeight, scrollHeight)
      textarea.style.height = `${newHeight}px`
    }
  }

  // Обновлен обработчик изменения сообщения
  const handleMessageChange = (e) => {
    const newValue = e.target.value
    if (isControlled && onChange) {
      onChange(newValue)
    } else {
      setInternalMessage(newValue)
    }
  }

  // Автоматически изменяем размер при изменении текста
  useEffect(() => {
    adjustTextareaHeight()
  }, [message, centered])

  // Также корректируем размер при монтировании компонента
  useEffect(() => {
    adjustTextareaHeight()
  }, [])

  const handleSubmit = (e) => {
    e.preventDefault()

    const trimmedMessage = message.trim()

    // Проверяем, что есть либо текст, либо файлы
    if ((trimmedMessage || files.length > 0) && !isLoading && !isAwaitingConfirmation) {
      // Если нет текста, но есть файлы, добавляем сообщение по умолчанию
      const messageToSend = trimmedMessage || (files.length > 0 ? `Отправлено файлов: ${files.length}` : "")

      if (messageToSend) {
        onSendMessage(messageToSend, files)
        // Сброс значения должен осуществляться родителем при controlled mode
        if (!isControlled) {
             setInternalMessage("")
        }      
        setFiles([])
        if (onClearFiles) {
          onClearFiles()
        }
      }
    }
  }

  const handleFileSelect = (e) => {
    const selectedFiles = Array.from(e.target.files)
    setFiles((prev) => [...prev, ...selectedFiles])
    // Сбрасываем значение инпута, чтобы можно было выбрать тот же файл повторно
    if (fileInputRef.current) {
        fileInputRef.current.value = ""
    }
  }

  const removeFile = (index) => {
    setFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
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
              <span className="text-sm text-gray-600">Прикреплено файлов: {files.length}</span>
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
                    <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
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
          <div
            className={`flex items-center gap-2 rounded-lg overflow-hidden transition-all ${
              centered
                ? "border-2 border-gray-300 focus-within:border-blue-500 focus-within:shadow-lg"
                : "border border-gray-300 focus-within:border-blue-500"
            }`}
          >
            {/* Кнопка прикрепления файлов */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isLoading || isAwaitingConfirmation}
              className={`p-3 transition-colors group flex-shrink-0 ${
                isLoading || isAwaitingConfirmation ? "text-gray-300 cursor-not-allowed" : "text-gray-500 hover:text-blue-500"
              }`}
              title={isLoading ? "Ожидание ответа..." : isAwaitingConfirmation ? "Подтвердите план действий" : "Прикрепить файл"}
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
                <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
              </svg>
            </button>

            {/* Поле ввода */}
            <textarea
              ref={textareaRef}
              value={message}
              onChange={handleMessageChange}
              onKeyDown={handleKeyDown}
              placeholder={
                isLoading
                  ? "Ожидание ответа..."
                  : isAwaitingConfirmation
                    ? "Подтвердите план действий выше, чтобы продолжить..."
                    : files.length > 0
                      ? "Добавьте описание к файлам (необязательно)..."
                      : centered
                        ? "Задайте ваш вопрос..."
                        : "Напишите сообщение..."
              }
              disabled={isLoading || isAwaitingConfirmation}
              className={`flex-1 resize-none border-0 outline-none overflow-y-auto chat-textarea ${
                centered ? "py-4 text-base" : "py-3"
              } ${isLoading || isAwaitingConfirmation ? "bg-gray-50 text-gray-400 cursor-not-allowed" : ""}`}
              style={{ 
                lineHeight: '1.5',
                scrollbarWidth: 'thin',
                scrollbarColor: '#cbd5e1 transparent'
              }}
              rows="1"
            />

            {/* Кнопка отправки */}
            <button
              type="submit"
              disabled={(!message.trim() && files.length === 0) || isLoading || isAwaitingConfirmation}
              className={`p-3 transition-colors group flex-shrink-0 ${
                (!message.trim() && files.length === 0) || isLoading || isAwaitingConfirmation
                  ? "text-gray-300 cursor-not-allowed"
                  : "text-blue-500 hover:text-blue-600"
              }`}
              title={isLoading ? "Ожидание ответа..." : isAwaitingConfirmation ? "Подтвердите план действий" : "Отправить сообщение"}
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
                  <path d="M21 12a9 9 0 11-6.219-8.56" />
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
                  <path d="m3 3 3 9-3 9 19-9Z" />
                  <path d="m6 12 15 0" />
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
            disabled={isLoading || isAwaitingConfirmation}
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
