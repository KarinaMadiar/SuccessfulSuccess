"use client"

import { LogOut } from "lucide-react"

import { useAuth } from "@/components/auth-provider"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { initials } from "@/lib/datetime"

export function UserMenu() {
  const { user, signOut } = useAuth()
  if (!user) return null

  const label = user.name ?? user.email ?? "Account"

  return (
    <div className="flex items-center gap-2">
      {user.email ? (
        <span className="hidden text-xs font-medium text-muted-foreground sm:inline-block bg-muted/70 px-2.5 py-1 rounded-full border">
          {user.email}
        </span>
      ) : null}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-lg" className="rounded-full" aria-label="Account menu">
            <Avatar className="size-9">
              <AvatarFallback className="tint-violet text-xs font-semibold">
                {initials(user.name ?? user.email?.split("@")[0] ?? "?")}
              </AvatarFallback>
            </Avatar>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-60">
          <DropdownMenuLabel className="font-normal">
            <p className="truncate text-sm font-semibold">{label}</p>
            {user.email && user.email !== label ? (
              <p className="text-muted-foreground truncate text-xs">{user.email}</p>
            ) : null}
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => void signOut()}>
            <LogOut aria-hidden />
            Sign out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Button variant="outline" size="sm" onClick={() => void signOut()} className="hidden sm:inline-flex">
        Sign out
      </Button>
    </div>
  )
}
