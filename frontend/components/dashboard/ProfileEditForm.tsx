'use client'

import React, { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import * as z from 'zod'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'
import { toast } from 'sonner'
import { OutreachProfile } from '@/types'

const profileFormSchema = z.object({
  account_name: z.string().optional(),
  linkedin_email: z.string().email({ message: "Invalid email address" }),
  linkedin_password: z.string().optional(),
  linkedin_url: z.string().url({ message: "Invalid URL" }),
  gohighlevel_location_id: z.string().optional(),
})

type ProfileFormValues = z.infer<typeof profileFormSchema>
type ProfileSubmissionData = Omit<ProfileFormValues, 'account_name' | 'gohighlevel_location_id' | 'linkedin_password'> & {
  account_name?: string
  gohighlevel_location_id?: string
  linkedin_password?: string
}

interface ProfileEditFormProps {
  profile: OutreachProfile
  onSubmit: (data: ProfileSubmissionData) => Promise<void>
  isSubmitting: boolean
}

export const ProfileEditForm: React.FC<ProfileEditFormProps> = ({
  profile,
  onSubmit,
  isSubmitting
}) => {
  const form = useForm<ProfileFormValues>({
    resolver: zodResolver(profileFormSchema),
    defaultValues: {
      account_name: profile.account_name || '',
      linkedin_email: profile.linkedin_email,
      linkedin_password: '', // Don't pre-fill password for security, but user must re-enter to update anything or leave blank? 
                             // The backend expects password if provided.
                             // Actually, for updates, usually password is optional if not changing. 
                             // My schema makes it optional, but here I made it required in z.object
                             // Let me adjust schema to allow empty password if they don't want to change it.
      linkedin_url: profile.linkedin_url,
      gohighlevel_location_id: profile.gohighlevel_location_id || '',
    },
  })

  // Need to handle password logic: 
  // 1. If user wants to keep existing password, they might leave it blank.
  // 2. But if I make it optional in schema, I need to handle that in submission.
  // My backend update endpoint handles optional fields.

  const handleSubmit = async (data: ProfileFormValues) => {
    try {
      // Clean up empty strings to undefined where appropriate
      const submissionData: ProfileSubmissionData = {
        ...data,
        account_name: data.account_name || undefined,
        gohighlevel_location_id: data.gohighlevel_location_id || undefined,
        // If password is empty string, don't send it (keep existing)
        linkedin_password: data.linkedin_password || undefined,
      }
      
      // If linkedin_password is explicitly required by my previous schema definition, I should change it.
      // Wait, the form schema above says min(1). I should change that to optional.
      
      await onSubmit(submissionData)
      toast.success('Profile updated successfully')
    } catch (error) {
      console.error(error)
      toast.error('Failed to update profile')
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile Settings</CardTitle>
        <CardDescription>
          Update your LinkedIn profile credentials and settings.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="account_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Account Name</FormLabel>
                  <FormControl>
                    <Input placeholder="My Personal Account" {...field} />
                  </FormControl>
                  <FormDescription>
                    A friendly name to identify this profile.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="linkedin_email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>LinkedIn Email</FormLabel>
                    <FormControl>
                      <Input placeholder="email@example.com" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              
              <FormField
                control={form.control}
                name="linkedin_password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>LinkedIn Password</FormLabel>
                    <FormControl>
                      <Input type="password" placeholder="••••••••" {...field} />
                    </FormControl>
                    <FormDescription>
                      Leave blank to keep current password.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="linkedin_url"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>LinkedIn Profile URL</FormLabel>
                  <FormControl>
                    <Input placeholder="https://www.linkedin.com/in/username" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="gohighlevel_location_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>GoHighLevel Location ID</FormLabel>
                  <FormControl>
                    <Input placeholder="Location ID" {...field} />
                  </FormControl>
                  <FormDescription>
                    Optional: Link this profile to a GHL location.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="flex justify-end">
                <Button type="submit" disabled={isSubmitting}>
                  {isSubmitting ? 'Saving...' : 'Save Changes'}
                </Button>
            </div>
          </form>
        </Form>
      </CardContent>
    </Card>
  )
}
