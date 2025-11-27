import { apiClient } from './client'
import { Client, ClientCampaignSummary, ClientProfileSummary } from '@/types'

export const clients_api = {
  list_clients: async (): Promise<Client[]> => {
    const response = await apiClient.get<Client[]>('/admin/users')
    return response.data
  },

  get_client_by_id: async (id: number): Promise<Client> => {
    const response = await apiClient.get<Client>(`/admin/users/${id}`)
    return response.data
  },

  update_client: async (id: number, data: { email?: string; is_admin?: boolean }): Promise<Client> => {
    const response = await apiClient.put<Client>(`/admin/users/${id}`, data)
    return response.data
  },

  delete_client: async (id: number): Promise<void> => {
    await apiClient.delete(`/admin/users/${id}`)
  },

  get_client_profiles: async (client_id: number): Promise<ClientProfileSummary[]> => {
    const response = await apiClient.get<ClientProfileSummary[]>(`/admin/users/${client_id}/profiles`)
    return response.data
  },

  get_client_campaigns: async (client_id: number): Promise<ClientCampaignSummary[]> => {
    const response = await apiClient.get<ClientCampaignSummary[]>(`/admin/users/${client_id}/campaigns`)
    return response.data
  },
}




