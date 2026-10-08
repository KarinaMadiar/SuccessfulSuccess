"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"
import { signInWithRedirect } from "aws-amplify/auth"

import { useAuth } from "@/components/auth-provider"
import { AuthLoading } from "@/components/require-auth"
import { configureAuth, isAuthConfigured } from "@/lib/auth"

export default function LoginPage() {
  const { status } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (status === "signedIn") {
      router.replace("/")
      return
    }
    if (status === "signedOut" && isAuthConfigured) {
      configureAuth()
      void signInWithRedirect()
    }
  }, [status, router])

  return <AuthLoading label="Redirecting to sign-in…" />
}
