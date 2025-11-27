'use client'

import React, { useState } from 'react'
import { useWizard } from '@/lib/context/WizardContext'
import { useCampaignTemplates, useCreateTemplate } from '@/lib/hooks/useCampaigns'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'

interface CampaignTemplateStepProps {
  on_next: () => void
  on_back: () => void
}

interface StepForm {
  step_number: number
  action: 'send_connection' | 'send_message'
  additional_note_template?: string
  message_template?: string
  delay_days: number
  delay_hours: number
  delay_minutes: number
}

export const CampaignTemplateStep: React.FC<CampaignTemplateStepProps> = ({
  on_next,
}) => {
  const { state, update_state } = useWizard()
  const { data: templates, isLoading } = useCampaignTemplates(state.clientAccessToken)
  const create_template = useCreateTemplate(state.clientAccessToken || '')
  
  const [show_form, set_show_form] = useState(false)
  const [template_name, set_template_name] = useState('')
  const [template_description, set_template_description] = useState('')
  const [steps, set_steps] = useState<StepForm[]>([
    {
      step_number: 1,
      action: 'send_connection',
      additional_note_template: '',
      delay_days: 0,
      delay_hours: 0,
      delay_minutes: 0,
    }
  ])

  const extract_variables = (text: string): string[] => {
    const regex = /\{\{([^}]+)\}\}/g
    const matches = text.matchAll(regex)
    return Array.from(new Set(Array.from(matches, m => m[1].trim())))
  }

  const get_all_variables = (): string[] => {
    const all_vars: string[] = []
    steps.forEach(step => {
      if (step.additional_note_template) {
        all_vars.push(...extract_variables(step.additional_note_template))
      }
      if (step.message_template) {
        all_vars.push(...extract_variables(step.message_template))
      }
    })
    return Array.from(new Set(all_vars))
  }

  const handle_select_template = (template_id: number) => {
    const template = templates?.find(t => t.id === template_id)
    if (template) {
      update_state({
        campaignTemplateId: template_id,
        // Variables are extracted from step templates when the template is loaded
        // For now, we set empty and let the campaign runner extract them
        requiredVariables: [],
      })
      toast.success('Template selected')
      on_next()
    }
  }

  const add_step = () => {
    set_steps([...steps, {
      step_number: steps.length + 1,
      action: 'send_message',
      message_template: '',
      delay_days: 2,
      delay_hours: 0,
      delay_minutes: 0,
    }])
  }

  const remove_step = (index: number) => {
    if (steps.length > 1) {
      const new_steps = steps.filter((_, i) => i !== index)
      new_steps.forEach((step, i) => {
        step.step_number = i + 1
      })
      set_steps(new_steps)
    }
  }

  const update_step = <K extends keyof StepForm>(index: number, field: K, value: StepForm[K]) => {
    const new_steps = [...steps]
    new_steps[index] = { ...new_steps[index], [field]: value }
    set_steps(new_steps)
  }

  const format_delay = (step: StepForm): string => {
    const { delay_days, delay_hours, delay_minutes } = step
    if (delay_days === 0 && delay_hours === 0 && delay_minutes === 0) {
      return '0:00:00'
    }
    let result = ''
    if (delay_days > 0) result += `${delay_days}d`
    if (delay_hours > 0) result += `${delay_hours}h`
    if (delay_minutes > 0) result += `${delay_minutes}m`
    return result || '0:00:00'
  }

  const handle_create_template = async () => {
    if (!template_name.trim()) {
      toast.error('Please provide a template name')
      return
    }

    if (!state.clientAccessToken) {
      toast.error('No client token available')
      return
    }

    const formatted_steps = steps.map(step => ({
      step_number: step.step_number,
      action: step.action,
      ...(step.action === 'send_connection' && step.additional_note_template
        ? { additional_note_template: step.additional_note_template }
        : {}),
      ...(step.action === 'send_message' && step.message_template
        ? { message_template: step.message_template }
        : {}),
      delay_timestamp: format_delay(step),
    }))

    try {
      const new_template = await create_template.mutateAsync({
        name: template_name,
        description: template_description,
        steps: formatted_steps,
      })

      const variables = get_all_variables()
      update_state({
        campaignTemplateId: new_template.id,
        requiredVariables: variables,
      })

      toast.success('Template created successfully')
      on_next()
    } catch (error: unknown) {
      const message =
        (error as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        (error instanceof Error ? error.message : 'Failed to create template')
      toast.error(message)
    }
  }

  if (isLoading) {
    return (
      <div className="text-center py-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mx-auto"></div>
        <p className="mt-2 text-gray-600">Loading templates...</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {!show_form && templates && templates.length > 0 && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="text-lg font-medium">Select Existing Template</h3>
            <Button variant="outline" onClick={() => set_show_form(true)}>
              Create New Template
            </Button>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {templates.map((template) => (
              <Card
                key={template.id}
                className={`cursor-pointer transition-all hover:shadow-lg ${
                  state.campaignTemplateId === template.id
                    ? 'ring-2 ring-blue-500'
                    : ''
                }`}
                onClick={() => handle_select_template(template.id)}
              >
                <CardHeader>
                  <CardTitle className="text-lg">{template.name}</CardTitle>
                </CardHeader>
                <CardContent>
                  {template.description && (
                    <p className="text-sm text-gray-600 mb-2">{template.description}</p>
                  )}
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge variant="secondary">{template.number_of_steps} steps</Badge>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {(show_form || !templates || templates.length === 0) && (
        <div className="space-y-6">
          <div className="flex justify-between items-center">
            <h3 className="text-lg font-medium">Create Campaign Template</h3>
            {templates && templates.length > 0 && (
              <Button variant="outline" onClick={() => set_show_form(false)}>
                Use Existing Template
              </Button>
            )}
          </div>

          <div className="space-y-4">
            <div>
              <Label htmlFor="template-name">Template Name *</Label>
              <Input
                id="template-name"
                value={template_name}
                onChange={(e) => set_template_name(e.target.value)}
                placeholder="e.g., Tech Recruiter Outreach"
                disabled={create_template.isPending}
              />
            </div>

            <div>
              <Label htmlFor="template-description">Description (Optional)</Label>
              <Input
                id="template-description"
                value={template_description}
                onChange={(e) => set_template_description(e.target.value)}
                placeholder="Brief description of this campaign"
                disabled={create_template.isPending}
              />
            </div>

            <Separator />

            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <h4 className="font-medium">Campaign Steps</h4>
                <Button size="sm" variant="outline" onClick={add_step}>
                  Add Step
                </Button>
              </div>

              {steps.map((step, index) => (
                <Card key={index}>
                  <CardHeader>
                    <div className="flex justify-between items-center">
                      <CardTitle className="text-base">
                        Step {step.step_number}
                      </CardTitle>
                      {steps.length > 1 && (
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => remove_step(index)}
                        >
                          Remove
                        </Button>
                      )}
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div>
                      <Label>Action Type</Label>
                      <Select
                        value={step.action}
                        onValueChange={(value) =>
                          update_step(index, 'action', value as 'send_connection' | 'send_message')
                        }
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="send_connection">
                            Send Connection Request
                          </SelectItem>
                          <SelectItem value="send_message">
                            Send Message
                          </SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    {step.action === 'send_connection' && (
                      <div>
                        <Label>Connection Note (Optional)</Label>
                        <Textarea
                          value={step.additional_note_template}
                          onChange={(e) =>
                            update_step(index, 'additional_note_template', e.target.value)
                          }
                          placeholder="Hi {{first_name}}, I'd love to connect!"
                          rows={3}
                        />
                      </div>
                    )}

                    {step.action === 'send_message' && (
                      <div>
                        <Label>Message Template</Label>
                        <Textarea
                          value={step.message_template}
                          onChange={(e) =>
                            update_step(index, 'message_template', e.target.value)
                          }
                          placeholder="Hi {{first_name}}, thanks for connecting!"
                          rows={4}
                        />
                      </div>
                    )}

                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <Label>Days</Label>
                        <Input
                          type="number"
                          min="0"
                          value={step.delay_days}
                          onChange={(e) =>
                            update_step(index, 'delay_days', parseInt(e.target.value) || 0)
                          }
                          disabled={index === 0}
                        />
                      </div>
                      <div>
                        <Label>Hours</Label>
                        <Input
                          type="number"
                          min="0"
                          max="23"
                          value={step.delay_hours}
                          onChange={(e) =>
                            update_step(index, 'delay_hours', parseInt(e.target.value) || 0)
                          }
                          disabled={index === 0}
                        />
                      </div>
                      <div>
                        <Label>Minutes</Label>
                        <Input
                          type="number"
                          min="0"
                          max="59"
                          value={step.delay_minutes}
                          onChange={(e) =>
                            update_step(index, 'delay_minutes', parseInt(e.target.value) || 0)
                          }
                          disabled={index === 0}
                        />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>

            {get_all_variables().length > 0 && (
              <div className="bg-blue-50 p-4 rounded-lg">
                <h4 className="font-medium mb-2">Detected Variables:</h4>
                <div className="flex gap-2 flex-wrap">
                  {get_all_variables().map((variable) => (
                    <Badge key={variable} variant="secondary">
                      {variable}
                    </Badge>
                  ))}
                </div>
                <p className="text-sm text-gray-600 mt-2">
                  These variables must be provided for each target in the next step.
                </p>
              </div>
            )}

            <Button
              onClick={handle_create_template}
              disabled={create_template.isPending}
              className="w-full"
            >
              {create_template.isPending ? 'Creating Template...' : 'Create Template & Continue'}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}


