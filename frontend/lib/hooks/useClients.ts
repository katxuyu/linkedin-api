import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { clients_api } from '@/lib/api/clients'
import { Client, ClientCampaignSummary, ClientProfileSummary } from '@/types'
import { toast } from 'sonner'
import { AxiosError } from 'axios'

type UseClientsOptions = {
  enabled?: boolean
}

export const useClients = (options?: UseClientsOptions) => {
  return useQuery({
    queryKey: ['clients'],
    queryFn: () => clients_api.list_clients(),
    enabled: options?.enabled ?? true,
  })
}

export const useClientById = (id: number | null) => {
  return useQuery({
    queryKey: ['client', id],
    queryFn: () => clients_api.get_client_by_id(id!),
    enabled: !!id,
  })
}

export const useUpdateClient = () => {
  const query_client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: { email?: string; is_admin?: boolean } }) =>
      clients_api.update_client(id, data),
    onSuccess: (data, variables) => {
      query_client.invalidateQueries({ queryKey: ['clients'] })
      query_client.invalidateQueries({ queryKey: ['client', variables.id] })
      toast.success('Client updated successfully')
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast.error(error.response?.data?.detail || error.message || 'Failed to update client')
    },
  })
}

export const useDeleteClient = () => {
  const query_client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => clients_api.delete_client(id),
    onSuccess: () => {
      query_client.invalidateQueries({ queryKey: ['clients'] })
      toast.success('Client deleted successfully')
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast.error(error.response?.data?.detail || error.message || 'Failed to delete client')
    },
  })
}

export const useClientProfiles = (client_id: number | null) => {
  return useQuery({
    queryKey: ['client-profiles', client_id],
    queryFn: () => clients_api.get_client_profiles(client_id!),
    enabled: !!client_id,
  })
}

export const useClientCampaigns = (client_id: number | null) => {
  return useQuery({
    queryKey: ['client-campaigns', client_id],
    queryFn: () => clients_api.get_client_campaigns(client_id!),
    enabled: !!client_id,
  })
}


