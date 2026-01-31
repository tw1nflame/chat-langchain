"use client"

import { useEffect, useRef } from "react"
import Message from "./Message"

function MessageList({ messages, chatId, onConfirm }) {
  const messagesEndRef = useRef(null)

  // Debug: log messages array on render
  try {
    // eslint-disable-next-line no-console
    console.debug("[MessageList] render messages count:", messages?.length, messages)
  } catch (e) {}

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto py-6 px-4">
        {messages.map((message) => (
          <Message key={message.id} message={message} chatId={chatId} onConfirm={onConfirm} />
        ))}
        <div ref={messagesEndRef} />
      </div>
    </div>
  )
}

export default MessageList
