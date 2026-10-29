"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { AlertCircle, CalendarIcon, Loader2, Sparkles, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { Controller, useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { ParticipantsInput } from "@/components/participants-input"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Calendar } from "@/components/ui/calendar"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Separator } from "@/components/ui/separator"
import { Textarea } from "@/components/ui/textarea"
import { useCreateMeeting, useUpdateMeeting } from "@/hooks/use-meetings"
import { ApiError, parseAgendaText } from "@/lib/api"
import { formatTime, parseIsoDay, toIsoDate, toIsoWithOffset } from "@/lib/datetime"
import type { AiSuggestion, Meeting, ParsedAgenda } from "@/lib/types"

const timePattern = /^([01]\d|2[0-3]):([0-5]\d)$/

const participantSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(120, "Name is too long"),
  email: z
    .string()
    .trim()
    .max(255)
    .refine((value) => value === "" || z.email().safeParse(value).success, {
      message: "Enter a valid email address",
    })
    .optional(),
})

const formSchema = z
  .object({
    name: z.string().trim().min(1, "Name is required").max(200, "Name is too long"),
    description: z.string().trim().max(2000, "Description is too long").optional(),
    location: z.string().trim().max(200, "Location is too long").optional(),
    date: z.date(),
    startTime: z.string().regex(timePattern, "Use HH:mm"),
    endTime: z.string().regex(timePattern, "Use HH:mm"),
    participants: z.array(participantSchema).max(50, "At most 50 participants"),
  })
  .refine((data) => data.endTime > data.startTime, {
    message: "The meeting must end after it starts",
    path: ["endTime"],
  })
  .refine(
    (data) => {
      const keys = data.participants.map(
        (p) => `${p.name.trim().toLowerCase()}|${(p.email ?? "").trim().toLowerCase()}`,
      )
      return new Set(keys).size === keys.length
    },
    { message: "Participants must be unique", path: ["participants"] },
  )

type FormValues = z.infer<typeof formSchema>
type SuggestedField = "name" | "description" | "date" | "startTime" | "endTime" | "participants"

type ParticipantErrors = { name?: { message?: string }; email?: { message?: string } }

/** Flattens react-hook-form's per-row participant errors into { rowIndex: message }. */
function participantErrors(rows: unknown): Record<number, string | undefined> {
  if (!Array.isArray(rows)) return {}
  return Object.fromEntries(
    rows.map((row: ParticipantErrors | undefined, index: number) => [
      index,
      row?.name?.message ?? row?.email?.message,
    ]),
  )
}

/** Formats ParsedAgenda items and action items into structured agenda text. */
function formatAgendaText(agenda: ParsedAgenda): string {
  const lines: string[] = []
  if (agenda.items.length > 0) {
    lines.push("Agenda:")
    agenda.items.forEach((item, idx) => {
      const parts = [`${idx + 1}. ${item.topic}`]
      if (item.owner) parts.push(`— ${item.owner}`)
      if (item.minutes) parts.push(`(${item.minutes} min)`)
      lines.push(parts.join(" "))
    })
  }
  if (agenda.action_items.length > 0) {
    if (lines.length > 0) lines.push("")
    lines.push("Action items:")
    agenda.action_items.forEach((act) => {
      const parts = [`- [ ] ${act.task}`]
      if (act.owner) parts.push(`— ${act.owner}`)
      if (act.due) parts.push(`(due ${act.due})`)
      lines.push(parts.join(" "))
    })
  }
  return lines.join("\n").slice(0, 2000)
}

function addMinutesToTime(hhmm: string, minutes: number): string {
  const [h, m] = hhmm.split(":").map(Number)
  const total = Math.min(23 * 60 + 59, (h ?? 10) * 60 + (m ?? 0) + minutes)
  const endH = String(Math.floor(total / 60)).padStart(2, "0")
  const endM = String(total % 60).padStart(2, "0")
  return `${endH}:${endM}`
}

/** Blank form for a new meeting, or the meeting's current values when editing. */
function defaultValues(meeting?: Meeting): FormValues {
  if (!meeting) {
    return {
      name: "",
      description: "",
      location: "",
      date: new Date(),
      startTime: "10:00",
      endTime: "11:00",
      participants: [{ name: "", email: "" }],
    }
  }
  return {
    name: meeting.name,
    description: meeting.description ?? "",
    location: meeting.location ?? "",
    date: parseIsoDay(meeting.starts_at),
    startTime: formatTime(meeting.starts_at),
    endTime: formatTime(meeting.ends_at),
    participants:
      meeting.participants.length > 0
        ? meeting.participants.map((p) => ({ name: p.name, email: p.email ?? "" }))
        : [{ name: "", email: "" }],
  }
}

function SuggestedBadge({ show }: { show: boolean }) {
  if (!show) return null
  return (
    <Badge variant="secondary" className="tint-violet ml-2 px-2 py-0 text-[11px] font-medium">
      suggested
    </Badge>
  )
}

/** Creates a meeting, or edits `meeting` when one is passed, with AI "Paste an agenda" support. */
export function MeetingFormDialog({
  open,
  onOpenChange,
  meeting,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  meeting?: Meeting
}) {
  const createMeeting = useCreateMeeting()
  const updateMeeting = useUpdateMeeting()
  const [datePickerOpen, setDatePickerOpen] = useState(false)
  const [pastedText, setPastedText] = useState("")
  const [isParsing, setIsParsing] = useState(false)
  const [parseError, setParseError] = useState<string | null>(null)
  const [aiSuggestion, setAiSuggestion] = useState<AiSuggestion | null>(null)
  const [suggestedFields, setSuggestedFields] = useState<Set<SuggestedField>>(new Set())
  const abortRef = useRef<AbortController | null>(null)
  const isEdit = !!meeting

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: defaultValues(meeting),
  })

  const {
    register,
    handleSubmit,
    control,
    reset,
    setValue,
    getValues,
    setError,
    formState: { errors, isSubmitting },
  } = form

  const clearSuggested = (field: SuggestedField) => {
    setSuggestedFields((prev) => {
      if (!prev.has(field)) return prev
      const next = new Set(prev)
      next.delete(field)
      return next
    })
  }

  // Refill the form each time it opens, so edits start from the meeting's current values.
  useEffect(() => {
    if (open) reset(defaultValues(meeting))
  }, [open, meeting, reset])

  const handleDialogOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      abortRef.current?.abort()
      setIsParsing(false)
      setPastedText("")
      setParseError(null)
      setAiSuggestion(null)
      setSuggestedFields(new Set())
    }
    onOpenChange(nextOpen)
  }

  const handleParseAgenda = async () => {
    if (!pastedText.trim()) {
      setParseError("Paste an email, chat message or meeting notes first.")
      return
    }
    setParseError(null)
    setIsParsing(true)
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const todayIso = toIsoDate(new Date())
      const userTz = Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Kyiv"
      const result = await parseAgendaText(pastedText, todayIso, userTz, controller.signal)
      const { agenda } = result
      const filled = new Set<SuggestedField>()

      if (agenda.title) {
        setValue("name", agenda.title, { shouldValidate: true })
        filled.add("name")
      }

      const formattedDescription = formatAgendaText(agenda)
      if (formattedDescription) {
        setValue("description", formattedDescription, { shouldValidate: true })
        filled.add("description")
      }

      let baseStart = getValues("startTime")
      if (agenda.starts_at) {
        const parsedDay = parseIsoDay(agenda.starts_at)
        if (!Number.isNaN(parsedDay.getTime())) {
          setValue("date", parsedDay, { shouldValidate: true })
          filled.add("date")
        }
        const extractedTime = formatTime(agenda.starts_at)
        if (timePattern.test(extractedTime)) {
          baseStart = extractedTime
          setValue("startTime", extractedTime, { shouldValidate: true })
          filled.add("startTime")
        }
      }

      if (agenda.duration_minutes) {
        const computedEnd = addMinutesToTime(baseStart, agenda.duration_minutes)
        setValue("endTime", computedEnd, { shouldValidate: true })
        filled.add("endTime")
      } else if (agenda.items.some((i) => i.minutes)) {
        const totalItemMinutes = agenda.items.reduce((acc, i) => acc + (i.minutes ?? 0), 0)
        if (totalItemMinutes > 0) {
          const computedEnd = addMinutesToTime(baseStart, totalItemMinutes)
          setValue("endTime", computedEnd, { shouldValidate: true })
          filled.add("endTime")
        }
      }

      // Extract unique owners from agenda items and action items into participants
      const owners = new Map<string, { name: string; email: string }>()
      for (const ownerRaw of [
        ...agenda.items.map((i) => i.owner),
        ...agenda.action_items.map((a) => a.owner),
      ]) {
        if (!ownerRaw || !ownerRaw.trim()) continue
        const trimmed = ownerRaw.trim()
        const key = trimmed.toLowerCase()
        if (!owners.has(key)) {
          const isEmail = trimmed.includes("@")
          owners.set(key, {
            name: isEmail ? (trimmed.split("@")[0] || trimmed) : trimmed,
            email: isEmail ? trimmed : "",
          })
        }
      }
      if (owners.size > 0) {
        setValue("participants", Array.from(owners.values()), { shouldValidate: true })
        filled.add("participants")
      }

      setAiSuggestion(result)
      setSuggestedFields(filled)
      toast.success("Agenda parsed — check the suggested fields and press Save.")
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        toast.info("Agenda parsing cancelled.")
      } else if (err instanceof ApiError) {
        setParseError(err.message)
      } else {
        setParseError("Could not parse the agenda. You can fill in the form by hand.")
      }
    } finally {
      setIsParsing(false)
      abortRef.current = null
    }
  }

  const handleCancelParse = () => {
    abortRef.current?.abort()
    setIsParsing(false)
  }

  const onSubmit = handleSubmit(async (values) => {
    const participants = values.participants
      .filter((participant) => participant.name.trim() !== "")
      .map((participant) => ({
        name: participant.name.trim(),
        email: participant.email?.trim() ? participant.email.trim() : null,
      }))

    const payload = {
      name: values.name.trim(),
      description: values.description?.trim() || null,
      location: values.location?.trim() || null,
      starts_at: toIsoWithOffset(values.date, values.startTime),
      ends_at: toIsoWithOffset(values.date, values.endTime),
      participants,
      ...(aiSuggestion ? { ai_suggestion: aiSuggestion } : {}),
    }

    try {
      if (meeting) {
        await updateMeeting.mutateAsync({ id: meeting.id, payload })
        toast.success("Meeting updated")
      } else {
        await createMeeting.mutateAsync(payload)
        toast.success("Meeting created")
      }
      setPastedText("")
      setParseError(null)
      setAiSuggestion(null)
      setSuggestedFields(new Set())
      onOpenChange(false)
    } catch (error) {
      if (error instanceof ApiError) {
        // Map server-side field errors back onto the matching inputs.
        const fieldMap: Record<string, keyof FormValues> = {
          name: "name",
          description: "description",
          location: "location",
          starts_at: "startTime",
          ends_at: "endTime",
          participants: "participants",
        }
        for (const detail of error.details) {
          const target = fieldMap[detail.field.split(".")[0] ?? ""]
          if (target) setError(target, { message: detail.message })
        }
        toast.error(error.message)
      } else {
        toast.error(isEdit ? "Could not update the meeting." : "Could not create the meeting.")
      }
    }
  })

  const nameReg = register("name")
  const descReg = register("description")
  const startReg = register("startTime")
  const endReg = register("endTime")

  return (
    <Dialog open={open} onOpenChange={handleDialogOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit meeting & agenda" : "New meeting"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Paste an agenda to pre-fill with AI, or edit the details directly."
              : "Paste an email or chat message to pre-fill with AI, or enter details below."}
          </DialogDescription>
        </DialogHeader>

        {/* Paste an agenda (Part 4, Step 4) */}
        <div className="bg-muted/40 space-y-3 rounded-2xl border p-3.5">
          <div className="flex items-center justify-between gap-2">
            <Label htmlFor="paste-agenda" className="flex items-center gap-1.5 text-sm font-semibold">
              <Sparkles className="text-primary size-4" aria-hidden />
              Paste an agenda
            </Label>
            <span className="text-muted-foreground text-xs tabular-nums">
              {pastedText.length}/10,000
            </span>
          </div>
          <Textarea
            id="paste-agenda"
            rows={3}
            disabled={isParsing}
            value={pastedText}
            onChange={(e) => {
              setPastedText(e.target.value)
              if (parseError) setParseError(null)
            }}
            placeholder="Пн 10:00, синк по прайсингу, 45 хв. 1) нові тарифи Pro — Олена, 15 хв 2) фідбек від клієнтів — Taras..."
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            {isParsing ? (
              <div className="flex w-full items-center justify-between gap-2">
                <span className="text-muted-foreground inline-flex items-center gap-2 text-xs">
                  <Loader2 className="size-3.5 animate-spin" aria-hidden />
                  Parsing agenda with Claude on Bedrock (2–8 s)…
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleCancelParse}
                >
                  <X className="size-3.5" aria-hidden />
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={handleParseAgenda}
                disabled={!pastedText.trim()}
              >
                <Sparkles className="size-3.5" aria-hidden />
                Parse
              </Button>
            )}
          </div>
          {parseError ? (
            <Alert variant="destructive" className="py-2">
              <AlertCircle className="size-4" aria-hidden />
              <AlertDescription className="text-xs">{parseError}</AlertDescription>
            </Alert>
          ) : null}
        </div>

        <Separator />

        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name" className="flex items-center">
              Name
              <SuggestedBadge show={suggestedFields.has("name")} />
            </Label>
            <Input
              id="name"
              placeholder="Sprint planning"
              aria-invalid={!!errors.name}
              aria-describedby={errors.name ? "name-error" : undefined}
              {...nameReg}
              onChange={(e) => {
                clearSuggested("name")
                nameReg.onChange(e)
              }}
            />
            {errors.name ? (
              <p id="name-error" className="text-destructive text-sm">
                {errors.name.message}
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="description" className="flex items-center">
              Agenda / Description
              <SuggestedBadge show={suggestedFields.has("description")} />
            </Label>
            <Textarea
              id="description"
              rows={4}
              placeholder="What is this meeting about?"
              {...descReg}
              onChange={(e) => {
                clearSuggested("description")
                descReg.onChange(e)
              }}
            />
            {errors.description ? (
              <p className="text-destructive text-sm">{errors.description.message}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="location">Location</Label>
            <Input id="location" placeholder="Room 3 or a meeting link" {...register("location")} />
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-2 sm:col-span-1">
              <Label className="flex items-center">
                Date
                <SuggestedBadge show={suggestedFields.has("date")} />
              </Label>
              <Controller
                control={control}
                name="date"
                render={({ field }) => (
                  <Popover open={datePickerOpen} onOpenChange={setDatePickerOpen}>
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        className="w-full justify-start font-normal"
                      >
                        <CalendarIcon className="size-4" aria-hidden />
                        {toIsoDate(field.value)}
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-auto p-0" align="start">
                      <Calendar
                        mode="single"
                        selected={field.value}
                        onSelect={(date) => {
                          if (date) {
                            clearSuggested("date")
                            field.onChange(date)
                          }
                          setDatePickerOpen(false)
                        }}
                        autoFocus
                      />
                    </PopoverContent>
                  </Popover>
                )}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="startTime" className="flex items-center">
                Start
                <SuggestedBadge show={suggestedFields.has("startTime")} />
              </Label>
              <Input
                id="startTime"
                type="time"
                step={900}
                {...startReg}
                onChange={(e) => {
                  clearSuggested("startTime")
                  startReg.onChange(e)
                }}
              />
              {errors.startTime ? (
                <p className="text-destructive text-sm">{errors.startTime.message}</p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="endTime" className="flex items-center">
                End
                <SuggestedBadge show={suggestedFields.has("endTime")} />
              </Label>
              <Input
                id="endTime"
                type="time"
                step={900}
                {...endReg}
                onChange={(e) => {
                  clearSuggested("endTime")
                  endReg.onChange(e)
                }}
              />
              {errors.endTime ? (
                <p className="text-destructive text-sm">{errors.endTime.message}</p>
              ) : null}
            </div>
          </div>

          <div className="space-y-1">
            {suggestedFields.has("participants") ? (
              <div className="flex items-center">
                <SuggestedBadge show />
              </div>
            ) : null}
            <Controller
              control={control}
              name="participants"
              render={({ field }) => (
                <ParticipantsInput
                  value={field.value}
                  onChange={(next) => {
                    clearSuggested("participants")
                    field.onChange(next)
                  }}
                  errors={participantErrors(errors.participants)}
                />
              )}
            />
          </div>
          {errors.participants?.message ? (
            <p className="text-destructive text-sm">{errors.participants.message}</p>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => handleDialogOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isEdit
                ? isSubmitting
                  ? "Saving…"
                  : "Save changes"
                : isSubmitting
                  ? "Creating…"
                  : "Create meeting"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export const CreateMeetingDialog = MeetingFormDialog
