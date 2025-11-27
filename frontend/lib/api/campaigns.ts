import { apiClient } from './client'
import { CampaignTemplate, Campaign, TargetProfile, ImportStatus, CampaignHistoryResponse, CampaignTemplateResponse, CampaignDetailResponse, ScheduledTask, CampaignStep } from '@/types'

interface CreateTemplateData {
  name: string
  description?: string
  steps: CampaignStep[]
}

interface RunCampaignData {
  campaign_template_id: number
  outreach_profile_id: number
  target_profiles: TargetProfile[]
}

interface ImportSearchData {
  campaign_template_id: number
  outreach_profile_id: number
  search_url: string
  max_results: number
  search_filters?: Record<string, string>
}

interface ImportPreviewData {
  outreach_profile_id: number
  search_url: string
  max_results: number
}

export const campaigns_api = {
  list_campaigns: async (
    client_token: string,
    status?: string,
    limit: number = 100,
    offset: number = 0
  ): Promise<CampaignHistoryResponse[]> => {
    const params: { limit: number; offset: number; status?: string } = {
      limit,
      offset,
      ...(status ? { status } : {}),
    }
    const response = await apiClient.get<CampaignHistoryResponse[]>('/campaigns/list', {
      headers: {
        Authorization: `Bearer ${client_token}`
      },
      params
    })
    return response.data
  },

  list_templates: async (client_token: string): Promise<CampaignTemplateResponse[]> => {
    const response = await apiClient.get<CampaignTemplateResponse[]>('/campaigns/templates/list', {
      headers: {
        Authorization: `Bearer ${client_token}`
      }
    })
    return response.data
  },

  create_template: async (
    data: CreateTemplateData,
    client_token: string
  ): Promise<CampaignTemplate> => {
    const response = await apiClient.post<CampaignTemplate>(
      '/campaigns/templates/create',
      data,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  run_campaign: async (
    data: RunCampaignData,
    client_token: string
  ): Promise<{ status: string; message: string }> => {
    const response = await apiClient.post(
      '/campaigns/run',
      data,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  import_search_preview: async (
    data: ImportPreviewData,
    client_token: string
  ): Promise<{ total: number; targets: TargetProfile[] }> => {
    const response = await apiClient.post(
      '/campaigns/import-search/preview',
      data,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  import_search_run: async (
    data: ImportSearchData,
    client_token: string
  ): Promise<ImportStatus> => {
    const response = await apiClient.post<ImportStatus>(
      '/campaigns/import-search',
      data,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  get_import_status: async (
    import_id: string,
    client_token: string
  ): Promise<ImportStatus> => {
    const response = await apiClient.get<ImportStatus>(
      `/campaigns/import-search/${import_id}`,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  get_campaign_status: async (
    campaign_id: number,
    client_token: string
  ): Promise<Campaign> => {
    const response = await apiClient.get<Campaign>(
      `/campaigns/status/${campaign_id}`,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  pause_campaign: async (
    campaign_id: number,
    client_token: string
  ): Promise<{ status: string; message: string; campaign_history_id: number; cancelled_tasks_count: number; cancelled_watchers_count: number }> => {
    const response = await apiClient.post(
      `/campaigns/pause/${campaign_id}`,
      {},
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  get_campaign_detail: async (
    campaign_id: number,
    client_token: string
  ): Promise<CampaignDetailResponse> => {
    const response = await apiClient.get<CampaignDetailResponse>(
      `/campaigns/${campaign_id}`,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  get_scheduled_tasks: async (
    campaign_id: number,
    client_token: string
  ): Promise<ScheduledTask[]> => {
    const response = await apiClient.get<ScheduledTask[]>(
      `/campaigns/${campaign_id}/scheduled-tasks`,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  get_template_steps: async (
    template_id: number,
    client_token: string
  ): Promise<{ template_id: number; steps: Array<{ step_number: number; action: string; delay_days: number; message_template: string | null; variables: string[] | null }> }> => {
    const response = await apiClient.get(
      `/campaigns/templates/${template_id}/steps`,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  verify_targets_connection: async (
    outreach_profile_id: number,
    target_urls: string[],
    client_token: string
  ): Promise<{ status: string; results: Array<{ url: string; connected: boolean; pending: boolean; name?: string; error?: string }>; all_connected: boolean }> => {
    const response = await apiClient.post(
      '/campaigns/verify-targets-connection',
      null,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        },
        params: {
          outreach_profile_id,
          target_urls
        }
      }
    )
    return response.data
  },
}




