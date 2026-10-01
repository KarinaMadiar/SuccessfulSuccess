import { RequireAuth } from "@/components/require-auth"
import { TodayPage } from "@/components/today-page"

export const metadata = {
  title: "Today — SuccessfulSuccess",
}

export default function Today() {
  return (
    <RequireAuth>
      <TodayPage />
    </RequireAuth>
  )
}
