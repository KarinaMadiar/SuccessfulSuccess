"use client"

import { CalendarDays } from "lucide-react"

import { AuthPage } from "@/components/auth-page"
import { useAuth } from "@/components/auth-provider"
import { isAuthConfigured } from "@/lib/auth"

/** Full-screen placeholder while the session is checked. */
export function AuthLoading({ label = "Checking your session…" }: { label?: string }) {
  return (
    <div role="status" className="flex flex-1 flex-col items-center justify-center gap-4 py-24">
      <span
        className="flex size-12 animate-pulse items-center justify-center rounded-full text-white"
        style={{
          backgroundImage:
            "linear-gradient(135deg, var(--canva-teal), var(--canva-blue) 45%, var(--canva-violet))",
        }}
        aria-hidden
      >
        <CalendarDays className="size-5" />
      </span>
      <p className="text-muted-foreground text-sm">{label}</p>
    </div>
  )
}

/** Renders its children for a signed-in user; if auth is configured but signed out, shows the login page. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth()

  if (!isAuthConfigured) {
    return <>{children}</>
  }

  if (status === "loading") {
    return <AuthLoading />
  }

  if (status === "signedOut") {
    return <AuthPage />
  }

  return <>{children}</>
}
