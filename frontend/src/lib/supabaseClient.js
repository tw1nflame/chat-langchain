"use client"

import { createClient } from "@supabase/supabase-js"

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.VITE_SUPABASE_URL
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.VITE_SUPABASE_ANON_KEY

if (!supabaseUrl || !supabaseAnonKey) {
  console.warn("Supabase env variables not set: NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY")
}

// Debug: print which Supabase URL the frontend client was built with (do not print keys)
try {
  // Use console.debug so it's easy to filter in dev tools
  console.debug('[supabase.client] using supabaseUrl=', supabaseUrl || '<not-set>', 'anon_key_present=', !!supabaseAnonKey)
} catch (e) {
  // ignore logging failures
}

// Create supabase client with local persistence so session survives page reloads
// Create Supabase client with default auth persistence. Avoid forcing localStorage here; let the SDK pick a secure default.
// Use localStorage for auth so user remains logged in across browser restarts.
const storage = typeof window !== "undefined" && window.localStorage ? window.localStorage : undefined

export const supabase = createClient(supabaseUrl || "", supabaseAnonKey || "", {
  auth: {
    persistSession: true,
    storage,
  },
})

export async function getCurrentSession() {
  try {
    const { data } = await supabase.auth.getSession()
    return data?.session || null
  } catch (e) {
    console.warn("[supabase] getCurrentSession failed", e)
    return null
  }
}
