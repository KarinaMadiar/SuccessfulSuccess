// Mirrors the Pydantic schemas in backend/app/schemas/meeting.py.

export type Participant = {
  id: string
  name: string
  email: string | null
  position: number
}

export type AgendaItem = {
  topic: string
  owner: string | null
  minutes: number | null
}

export type ActionItem = {
  task: string
  owner: string | null
  due: string | null
}

export type ParsedAgenda = {
  title: string | null
  starts_at: string | null
  duration_minutes: number | null
  items: AgendaItem[]
  action_items: ActionItem[]
  language: string
}

export type AiSuggestion = {
  agenda: ParsedAgenda
  model: string
  prompt_version: string
}

export type Meeting = {
  id: string
  name: string
  description: string | null
  location: string | null
  starts_at: string
  ends_at: string
  participants: Participant[]
  ai_suggestion?: AiSuggestion | Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export type MeetingList = {
  items: Meeting[]
  total: number
  limit: number
  offset: number
  date: string
}

export type ParticipantInput = {
  name: string
  email?: string | null
}

export type MeetingCreateInput = {
  name: string
  description?: string | null
  location?: string | null
  starts_at: string
  ends_at: string
  participants: ParticipantInput[]
  ai_suggestion?: AiSuggestion | Record<string, unknown> | null
}

export type ApiErrorDetail = {
  field: string
  message: string
}

export type ApiErrorBody = {
  error: {
    code: string
    message: string
    details: ApiErrorDetail[]
  }
}

export type UserProfile = {
  id: string
  email: string | null
  email_verified: boolean
  name: string | null
  given_name: string | null
  family_name: string | null
  picture_url: string | null
  auth_provider: string
  created_at: string
  updated_at: string
  last_login_at: string | null
}
