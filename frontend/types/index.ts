export interface User {
  id: number
  email: string
  is_admin: boolean
  created_at: string
}

export interface OutreachProfile {
  id: number
  linkedin_url: string
  linkedin_email: string
  account_name?: string | null
  gohighlevel_location_id: string | null
}

export interface CampaignStep {
  step_number: number
  action: 'send_connection' | 'send_message'
  additional_note_template?: string
  message_template?: string
  delay_timestamp: string | {
    days?: number
    hours?: number
    minutes?: number
    seconds?: number
  }
}

export interface CampaignTemplate {
  id: number
  name: string
  description?: string
  steps: CampaignStep[]
  variables?: string[]
}

export interface TargetProfile {
  url: string
  variables: Record<string, string>
}

export interface Campaign {
  campaign_history_id: number
  runtime_id: string
  started_at: string
  modified_at: string
  status: 'active' | 'completed' | 'failed' | 'cancelled' | 'paused'
  latest_step: number
  total_steps: number
  details: Record<string, unknown>
}

export interface CampaignHistoryResponse {
  campaign_history_id: number
  runtime_id: string
  user_id: number
  outreach_profile_id: number
  target_profile_id: number
  campaign_template_id: number
  number_of_steps: number
  status: 'active' | 'completed' | 'failed' | 'cancelled' | 'paused'
  started_at: string
  modified_at: string
  finished_on_step_number: number | null
  target_profile_responded: boolean
  details: Record<string, unknown> | null
  target_profile_url?: string | null
  outreach_profile_email?: string | null
  template_name?: string | null
}

export interface CampaignTemplateResponse {
  id: number
  user_id: number
  name: string | null
  description: string | null
  number_of_steps: number
  created_at: string
}

export interface CampaignStepHistory {
  id: number
  campaign_history_id: number
  campaign_runtime_id: string
  step_number: number
  action: string
  status: string
  started_at: string
  modified_at: string
  details: Record<string, unknown> | null
}

export interface ScheduledTask {
  id: number
  campaign_history_id: number | null
  campaign_step_history_id: number | null
  target_profile_id: number
  step_number: number
  celery_task_id: string
  task_name: string
  scheduled_at: string
  status: string
  created_at: string
  executed_at: string | null
  details: Record<string, unknown> | null
}

export interface CampaignDetailResponse {
  campaign_history_id: number
  runtime_id: string
  user_id: number
  outreach_profile_id: number
  target_profile_id: number
  campaign_template_id: number
  number_of_steps: number
  status: 'active' | 'completed' | 'failed' | 'cancelled' | 'paused'
  started_at: string
  modified_at: string
  finished_on_step_number: number | null
  target_profile_responded: boolean
  details: Record<string, unknown> | null
  target_profile_url?: string | null
  outreach_profile_email?: string | null
  template_name?: string | null
  step_histories: CampaignStepHistory[]
}

export interface VerificationRequest {
  id: number
  outreach_profile_id: number
  status: 'pending' | 'completed' | 'expired' | 'failed'
  request_type: string
  expires_at: string
  remaining_seconds: number
  pending_reason: string
}

export interface LoginCodeAttempt {
  id: number
  request_id: number
  source: string
  submitted_by?: string | null
  submitted_by_user_id?: number | null
  code_value?: string | null
  two_captcha_used: boolean
  result?: string | null
  error_details?: string | null
  metadata?: Record<string, unknown> | null
  submitted_at: string
  processed_at?: string | null
}

export interface CodeRequestDetail {
  id: number
  outreach_profile_id: number
  outreach_email: string
  outreach_linkedin_url: string
  target_profile_id?: number | null
  target_name?: string | null
  target_url?: string | null
  campaign_history_id?: number | null
  status: string
  request_type: string
  expires_at: string
  remaining_seconds: number
  pending_reason?: string | null
  status_detail?: string | null
  resolved_at?: string | null
  last_status_at?: string | null
  two_captcha_job_id?: string | null
  metadata?: Record<string, unknown> | null
  created_at: string
  latest_attempt?: LoginCodeAttempt | null
  attempts: LoginCodeAttempt[]
}

export interface CodeRequestListResponse {
  pending: CodeRequestDetail[]
  succeeded: CodeRequestDetail[]
  errored: CodeRequestDetail[]
}

export interface AuthTokens {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface RegistrationKey {
  registration_key: string
}

export interface ImportStatus {
  import_id: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  search_url: string
  requested_lead_count: number
  total_extracted?: number
  total_imported?: number
  skipped?: number
  created_at: string
  started_at?: string
  finished_at?: string
}

export interface WizardState {
  selectedClientId: number | null
  clientEmail: string | null
  clientAccessToken: string | null
  outreachProfileId: number | null
  campaignTemplateId: number | null
  requiredVariables: string[]
  targetProfiles: TargetProfile[]
  importId: string | null
  importMethod: 'manual' | 'search' | null
}

export interface Client {
  id: number
  email: string
  is_admin: boolean
  created_at: string
  profile_count: number
  campaign_count: number
}

export interface ClientProfileSummary {
  id: number
  account_name?: string | null
  linkedin_email: string
  linkedin_url: string
  added_at: string
}

export interface ClientCampaignSummary {
  campaign_history_id: number
  runtime_id: string
  status: 'active' | 'completed' | 'failed' | 'cancelled' | 'paused'
  finished_on_step_number: number | null
  number_of_steps: number
  started_at: string
  modified_at: string
}

