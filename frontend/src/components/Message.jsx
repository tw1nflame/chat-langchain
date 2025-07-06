function Message({ message }) {
  const isUser = message.role === 'user'

  return (
    <div className={`mb-6 ${isUser ? 'flex justify-end' : ''}`}>
      {/* Содержимое сообщения */}
      <div className={`p-4 rounded-lg ${isUser ? 'flex-1' : ''} ${
        isUser 
          ? 'bg-blue-500 text-white' 
          : 'bg-white border border-gray-200'
      }`}>
        <p className={`whitespace-pre-wrap ${isUser ? 'text-white text-right' : 'text-gray-800'}`}>
          {message.content}
        </p>
        
        {/* Прикрепленные файлы */}
        {message.files && message.files.length > 0 && (
          <div className={`mt-3 pt-3 border-t ${isUser ? 'border-blue-400' : 'border-gray-200'}`}>
            <div className={`text-xs mb-2 ${isUser ? 'text-blue-100' : 'text-gray-500'}`}>
              Прикрепленные файлы:
            </div>
            {message.files.map((file, index) => (
              <div key={index} className="flex items-center gap-2 text-sm">
                <svg 
                  width="16" 
                  height="16" 
                  viewBox="0 0 24 24" 
                  fill="none" 
                  stroke="currentColor" 
                  strokeWidth="2" 
                  strokeLinecap="round" 
                  strokeLinejoin="round"
                  className={isUser ? 'text-blue-200' : 'text-gray-500'}
                >
                  <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
                </svg>
                <span className={isUser ? 'text-blue-100' : 'text-gray-600'}>
                  {file.name}
                </span>
                <span className={`text-xs ${isUser ? 'text-blue-200' : 'text-gray-500'}`}>
                  ({(file.size / 1024).toFixed(1)} KB)
                </span>
              </div>
            ))}
          </div>
        )}
        
        {/* Время отправки */}
        <div className={`text-xs mt-2 ${isUser ? 'text-blue-200 text-right' : 'text-gray-400'}`}>
          {message.timestamp.toLocaleTimeString()}
        </div>
      </div>
    </div>
  )
}

export default Message
