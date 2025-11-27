import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { campaigns_api } from '@/lib/api/campaigns'
import { CampaignStep, CampaignTemplate, TargetProfile } from '@/types'

export const useCampaignTemplates = (client_token: string | null) => {
  return useQuery({
    queryKey: ['campaign-templates', client_token],
    queryFn: () => campaigns_api.list_templates(client_token!),
    enabled: !!client_token,
  })
}

export const useCreateTemplate = (client_token: string) => {
  const query_client = useQueryClient()
  
  return useMutation({
    mutationFn: (data: { name: string; description?: string; steps: CampaignStep[] }) =>
      campaigns_api.create_template(data, client_token),
    onSuccess: () => {
      query_client.invalidateQueries({ queryKey: ['campaign-templates'] })
    },
  })
}

export const useRunCampaign = (client_token: string) => {
  return useMutation({
    mutationFn: (data: {
      campaign_template_id: number
      outreach_profile_id: number
      target_profiles: TargetProfile[]
    }) => campaigns_api.run_campaign(data, client_token),
  })
}

export const useImportSearchPreview = (client_token: string) => {
  return useMutation({
    mutationFn: (data: {
      outreach_profile_id: number
      search_url: string
      max_results: number
    }) => campaigns_api.import_search_preview(data, client_token),
  })
}

export const useImportSearchRun = (client_token: string) => {
  return useMutation({
    mutationFn: (data: {
      campaign_template_id: number
      outreach_profile_id: number
      search_url: string
      max_results: number
      search_filters?: Record<string, string>
    }) => campaigns_api.import_search_run(data, client_token),
  })
}

export const useImportStatus = (import_id: string | null, client_token: string | null) => {
  return useQuery({
    queryKey: ['import-status', import_id, client_token],
    queryFn: () => campaigns_api.get_import_status(import_id!, client_token!),
    enabled: !!import_id && !!client_token,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'pending' || status === 'in_progress') {
        return 3000
      }
      return false
    },
  })
}

export const useCampaignStatus = (campaign_id: number | null, client_token: string | null) => {
  return useQuery({
    queryKey: ['campaign-status', campaign_id, client_token],
    queryFn: () => campaigns_api.get_campaign_status(campaign_id!, client_token!),
    enabled: !!campaign_id && !!client_token,
    refetchInterval: 5000,
  })
}




