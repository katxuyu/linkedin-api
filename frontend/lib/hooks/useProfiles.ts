import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { profiles_api } from '@/lib/api/profiles'
import { UpdateProfileData } from '@/lib/api/profiles'

export const useOutreachProfiles = (client_token: string | null) => {
  return useQuery({
    queryKey: ['outreach-profiles', client_token],
    queryFn: () => profiles_api.list_outreach_profiles(client_token!),
    enabled: !!client_token,
  })
}

export const useRegisterProfile = (client_token: string) => {
  const query_client = useQueryClient()
  
  return useMutation({
    mutationFn: (data: {
      linkedin_email: string
      linkedin_password: string
      linkedin_url: string
      account_name?: string | null
      gohighlevel_location_id?: string | null
    }) => profiles_api.register_outreach_profile(data, client_token),
    onSuccess: () => {
      query_client.invalidateQueries({ queryKey: ['outreach-profiles'] })
    },
  })
}

export const useVerifyProfile = (client_token: string) => {
  const query_client = useQueryClient()
  
  return useMutation({
    mutationFn: (profile_id: number) => profiles_api.verify_profile_connection(profile_id, client_token),
    onSuccess: (_, profile_id) => {
       query_client.invalidateQueries({ queryKey: ['profile-status', profile_id] })
       query_client.invalidateQueries({ queryKey: ['profiles-status-bulk'] })
       query_client.invalidateQueries({ queryKey: ['outreach-profiles'] })
    }
  })
}

export const useSubmitPin = (client_token: string) => {
  const query_client = useQueryClient()
  
  return useMutation({
    mutationFn: ({ profile_id, pin }: { profile_id: number; pin: string }) => 
      profiles_api.submit_pin_verification(profile_id, pin, client_token),
    onSuccess: (_, { profile_id }) => {
       query_client.invalidateQueries({ queryKey: ['profile-status', profile_id] })
       query_client.invalidateQueries({ queryKey: ['profiles-status-bulk'] })
       query_client.invalidateQueries({ queryKey: ['outreach-profiles'] })
    }
  })
}

export const useDeleteProfile = (client_token: string) => {
  const query_client = useQueryClient()
  
  return useMutation({
    mutationFn: (profile_id: number) => profiles_api.delete_profile(profile_id, client_token),
    onSuccess: () => {
      query_client.invalidateQueries({ queryKey: ['outreach-profiles'] })
    },
  })
}

export const useUpdateProfile = (client_token: string) => {
  const query_client = useQueryClient()
  
  return useMutation({
    mutationFn: ({ profile_id, data }: { profile_id: number; data: UpdateProfileData }) => 
      profiles_api.update_profile_all_fields(profile_id, data, client_token),
    onSuccess: (data) => {
      query_client.invalidateQueries({ queryKey: ['outreach-profiles'] })
      query_client.invalidateQueries({ queryKey: ['profile-stats', data.id] })
      query_client.invalidateQueries({ queryKey: ['profile-status', data.id] })
    },
  })
}

export const useProfileStats = (client_token: string | null, profile_id: number | null) => {
  return useQuery({
    queryKey: ['profile-stats', profile_id, client_token],
    queryFn: () => profiles_api.get_profile_stats(profile_id!, client_token!),
    enabled: !!client_token && !!profile_id,
  })
}

export const useProfileStatus = (client_token: string | null, profile_id: number | null) => {
  return useQuery({
    queryKey: ['profile-status', profile_id, client_token],
    queryFn: () => profiles_api.get_profile_status(profile_id!, client_token!),
    enabled: !!client_token && !!profile_id,
    refetchInterval: 30000, 
  })
}

export const useProfilesStatusBulk = (client_token: string | null, profile_ids: number[]) => {
  return useQuery({
    queryKey: ['profiles-status-bulk', profile_ids, client_token],
    queryFn: () => profiles_api.get_profiles_status_bulk(profile_ids, client_token!),
    enabled: !!client_token && profile_ids.length > 0,
    refetchInterval: 30000,
  })
}




