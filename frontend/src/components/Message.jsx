import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { getCurrentSession } from "../lib/supabaseClient"

// Runtime-safe API base: prefer Next.js public env var, fallback to Vite-style, then localhost.
const API_BASE = 
  (typeof process !== 'undefined' && process.env && (process.env.NEXT_PUBLIC_API_BASE_URL || process.env.VITE_API_BASE_URL)) ||
  "http://localhost:8001"

function Message({ message }) {
  const isUser = message.role === "user"

  // Функция для получения иконки файла по типу
  const getFileIcon = (fileName, fileType) => {
    const extension = fileName.split(".").pop()?.toLowerCase()

    if (fileType?.includes("json") || extension === "json") {
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14,2 14,8 20,8" />
          <path d="M10 12h4" />
          <path d="M10 16h4" />
        </svg>
      )
    }

    if (fileType?.includes("text") || extension === "txt") {
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14,2 14,8 20,8" />
          <line x1="9" y1="9" x2="15" y2="9" />
          <line x1="9" y1="13" x2="15" y2="13" />
          <line x1="9" y1="17" x2="13" y2="17" />
        </svg>
      )
    }

    // Дефолтная иконка файла
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
      </svg>
    )
  }

  return (
    <div className={`mb-6 ${isUser ? "flex justify-end" : ""}`}>
      {/* Содержимое сообщения */}
      <div
        className={`p-4 rounded-lg ${isUser ? "flex-1" : ""} ${
          isUser ? "bg-blue-500 text-white" : "bg-white border border-gray-200"
        }`}
      >
        {/* Содержимое сообщения */}
        {isUser ? (
          <p className="text-white text-right whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose max-w-none text-gray-800">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
        )}

        {/* Прикрепленные файлы */}
        {message.files && message.files.length > 0 && (
          <div className={`mt-3 pt-3 border-t ${isUser ? "border-blue-400" : "border-gray-200"}`}>
            <div className={`text-xs mb-2 ${isUser ? "text-blue-100" : "text-gray-500"}`}>
              {isUser ? "Прикрепленные файлы:" : "Файлы от ассистента:"}
            </div>
            {message.files.map((file, index) => (
              <div key={index} className="flex items-center gap-2 text-sm mb-1">
                <div className={isUser ? "text-blue-200" : "text-gray-500"}>{getFileIcon(file.name, file.type)}</div>

                {/* Если есть download_url, делаем файл скачиваемым */}
                {file.download_url ? (
                  // Use a JS fetch to include Authorization header so backend can check owner.
                  <button
                    onClick={async (e) => {
                      e.preventDefault()
                      try {
                        const session = await getCurrentSession()
                        const token = session?.access_token
                        const headers = token ? { Authorization: `Bearer ${token}` } : {}
                        const resp = await fetch(`${API_BASE}${file.download_url}`, { headers })
                        if (!resp.ok) throw new Error(`File download failed: ${resp.status}`)
                        const blob = await resp.blob()
                        const url = window.URL.createObjectURL(blob)
                        const a = document.createElement('a')
                        a.href = url
                        a.download = file.name
                        document.body.appendChild(a)
                        a.click()
                        a.remove()
                        window.URL.revokeObjectURL(url)
                      } catch (err) {
                        console.error('Download failed', err)
                        // fallback: navigate to URL (may 401) so user sees error
                        window.open(`${API_BASE}${file.download_url}`, '_blank')
                      }
                    }}
                    className={`hover:underline cursor-pointer ${isUser ? "text-blue-100 hover:text-white" : "text-blue-600 hover:text-blue-800"}`}
                  >
                    {file.name}
                  </button>
                ) : (
                  <span className={isUser ? "text-blue-100" : "text-gray-600"}>{file.name}</span>
                )}

                <span className={`text-xs ${isUser ? "text-blue-200" : "text-gray-500"}`}>
                  ({file.size ? (file.size / 1024).toFixed(1) : "0"} KB)
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Время отправки */}
        <div className={`text-xs mt-2 ${isUser ? "text-blue-200 text-right" : "text-gray-400"}`}>
          {message.timestamp.toLocaleTimeString()}
        </div>
      </div>
    </div>
  )
}

export default Message
