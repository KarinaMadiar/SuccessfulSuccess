"use client"

import { MeetingFormDialog } from "@/components/meeting-form-dialog"
import type { Meeting } from "@/lib/types"

export function CreateMeetingDialog({
  open,
  onOpenChange,
  meeting,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  meeting?: Meeting
}) {
  return (
    <MeetingFormDialog
      open={open}
      onOpenChange={onOpenChange}
      meeting={meeting}
    />
  )
}

export { MeetingFormDialog }
