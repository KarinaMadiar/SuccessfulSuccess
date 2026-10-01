import { RequireAuth } from "@/components/require-auth"
import { TodayPage } from "@/components/today-page"

export const metadata = {
  title: "New meeting — SuccessfulSuccess",
}

/** Same screen as "/", with the create dialog already open. */
export default function NewMeetingPage() {
  return (
    <RequireAuth>
      <TodayPage initialDialogOpen />
    </RequireAuth>
  )
}
