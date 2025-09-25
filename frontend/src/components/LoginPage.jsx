"use client"

import { supabase } from "../lib/supabaseClient"
import { useState } from "react"

function LoginPage({ onLogin, onSwitchToRegister }) {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState("")

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError("")

    if (!email.trim() || !password.trim()) {
      setError("Пожалуйста, заполните все поля")
      return
    }

    setIsLoading(true)

    try {
      const { data, error } = await supabase.auth.signInWithPassword({ email, password })
      if (error) {
        setError(error.message || "Неверный email или пароль")
      } else if (data && data.user) {
        // Log that sign-in succeeded and whether session exists (do not print tokens)
        try {
          const sess = await supabase.auth.getSession()
          console.log('[LoginPage] signIn success, session_exists=', !!sess?.data?.session)
        } catch (e) {
          console.warn('[LoginPage] could not read session after sign-in', e)
        }
        onLogin({ email: data.user.email, name: data.user.user_metadata?.name || data.user.email })
      } else {
        setError("Не удалось выполнить вход")
      }
    } catch (err) {
      setError(err.message || "Ошибка при входе в систему")
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        <div>
          <h2 className="mt-6 text-center text-3xl font-bold text-gray-900">Вход в аккаунт</h2>
          <p className="mt-2 text-center text-sm text-gray-600">
            Или{" "}
            <button onClick={onSwitchToRegister} className="font-medium text-blue-600 hover:text-blue-500">
              создайте новый аккаунт
            </button>
          </p>
        </div>

        <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
          <div className="space-y-4">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-gray-700">
                Email адрес
              </label>
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={isLoading}
                className="mt-1 appearance-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 focus:z-10 sm:text-sm disabled:bg-gray-100"
                placeholder="Введите ваш email"
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700">
                Пароль
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isLoading}
                className="mt-1 appearance-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 focus:z-10 sm:text-sm disabled:bg-gray-100"
                placeholder="Введите ваш пароль"
              />
            </div>
          </div>

          {error && <div className="text-red-600 text-sm text-center bg-red-50 p-3 rounded-md">{error}</div>}

          <div>
            <button
              type="submit"
              disabled={isLoading}
              className="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:bg-blue-400 disabled:cursor-not-allowed"
            >
              {isLoading ? (
                <div className="flex items-center">
                  <svg
                    className="animate-spin -ml-1 mr-3 h-5 w-5 text-white"
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    ></circle>
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    ></path>
                  </svg>
                  Вход...
                </div>
              ) : (
                "Войти"
              )}
            </button>
          </div>

          <div className="text-center text-sm text-gray-600">
            <p>Для демонстрации используйте:</p>
            <p className="font-mono text-xs bg-gray-100 p-2 rounded mt-1">
              Email: user@example.com
              <br />
              Пароль: password
            </p>
          </div>
        </form>
      </div>
    </div>
  )
}

export default LoginPage
