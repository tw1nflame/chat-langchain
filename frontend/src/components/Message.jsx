"use client"

import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { getCurrentSession } from "../lib/supabaseClient"
import { useEffect, useRef } from "react"
// import vegaEmbed from "vega-embed" -> Moved to dynamic import

// Runtime-safe API base: prefer Next.js public env var, fallback to Vite-style, then localhost.
const API_BASE = 
  (typeof process !== 'undefined' && process.env && (process.env.NEXT_PUBLIC_API_BASE_URL || process.env.VITE_API_BASE_URL)) ||
  "http://localhost:8000"

const VegaChart = ({ spec, title, data }) => {
  const containerRef = useRef(null)

  useEffect(() => {
    if (containerRef.current && spec) {
      const embedOptions = {
        actions: { export: true, source: false, compiled: false, editor: false },
        renderer: "svg",
        mode: "vega-lite"
      }
      
      const finalSpec = JSON.parse(JSON.stringify(spec))
      
      let chartData = []
      if (data && data.headers && data.rows) {
          chartData = data.rows.map(row => {
              const obj = {}
              data.headers.forEach((h, i) => {
                  obj[h] = row[i]
              })
              return obj
          })
      }
      
       if (finalSpec.data && finalSpec.data.name === "table_data") {
           delete finalSpec.data.name
           finalSpec.data.values = chartData
       }
      
      // Dynamic import to avoid SSR issues and "proper object" serialization errors
      // if vega-embed exports non-serializable stuff or runs code at import time
      import("vega-embed").then((module) => {
          const embed = module.default
          embed(containerRef.current, finalSpec, embedOptions).catch(console.error)
      }).catch(console.error)
    }
  }, [spec, data])

  return (
    <div className="mb-4 bg-white p-2 rounded border border-gray-300">
      {title && <div className="font-semibold text-sm text-gray-700 mb-2 border-b pb-1">{title}</div>}
      <div ref={containerRef} className="w-full overflow-x-auto" />
    </div>
  )
}

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
            <Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown>
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

        {/* Таблицы */}
        {message.tables && message.tables.length > 0 && (
          <div className={`mt-3 pt-3 border-t ${isUser ? "border-blue-400" : "border-gray-200"}`}>
             <div className={`text-xs mb-2 ${isUser ? "text-blue-100" : "text-gray-500"}`}>
              {isUser ? "Таблицы:" : "Таблицы от ассистента:"}
            </div>
            {message.tables.map((table, index) => (
              <div key={index} className="mb-4 overflow-hidden rounded border border-gray-300 bg-white">
                {/* Заголовок и кнопка скачивания */}
                <div className="bg-gray-100 p-2 flex justify-between items-center border-b border-gray-300">
                  <span className="font-semibold text-sm text-gray-700">{table.title || `Таблица ${index + 1}`}</span>
                   {table.download_url && (
                    <button
                        onClick={async (e) => {
                            e.preventDefault();
                            try {
                                const session = await getCurrentSession();
                                const token = session?.access_token;
                                const headers = token ? { Authorization: `Bearer ${token}` } : {};
                                const resp = await fetch(`${API_BASE}${table.download_url}`, { headers });
                                if (!resp.ok) throw new Error(`File download failed: ${resp.status}`);
                                const blob = await resp.blob();
                                const url = window.URL.createObjectURL(blob);
                                const a = document.createElement('a');
                                a.href = url;
                                a.download = `${table.title || 'export'}.xlsx`;
                                document.body.appendChild(a);
                                a.click();
                                a.remove();
                                window.URL.revokeObjectURL(url);
                            } catch (err) {
                                console.error('Download failed', err);
                                window.open(`${API_BASE}${table.download_url}`, '_blank');
                            }
                        }}
                        className="text-xs bg-green-500 hover:bg-green-600 text-white py-1 px-2 rounded flex items-center gap-1"
                    >
                        Excel
                    </button>
                   )}
                </div>
                
                {/* Сама таблица */}
                <div className="overflow-x-auto max-h-60">
                    <table className="min-w-full text-sm text-left text-gray-500">
                        <thead className="text-xs text-gray-700 uppercase bg-gray-50 sticky top-0">
                            <tr>
                                {table.headers.map((header, idx) => (
                                    <th key={idx} scope="col" className="px-4 py-2 border-r last:border-r-0 border-gray-200">
                                        {header}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {table.rows.map((row, rowIdx) => (
                                <tr key={rowIdx} className="bg-white border-b hover:bg-gray-50">
                                    {row.map((cell, cellIdx) => (
                                        <td key={cellIdx} className="px-4 py-2 border-r last:border-r-0 border-gray-200 whitespace-nowrap">
                                            {typeof cell === 'object' ? JSON.stringify(cell) : String(cell)}
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Charts */}
        {message.charts && message.charts.length > 0 && (
            <div className={`mt-3 pt-3 border-t ${isUser ? "border-blue-400" : "border-gray-200"}`}>
                <div className={`text-xs mb-2 ${isUser ? "text-blue-100" : "text-gray-500"}`}>
                 {isUser ? "Графики:" : "Графики от ассистента:"}
                </div>
                {message.charts.map((chart, index) => (
                    <VegaChart 
                        key={chart.id || index} 
                        spec={chart.spec} 
                        title={chart.title} 
                        data={message.tables && message.tables[0]} 
                    />
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
