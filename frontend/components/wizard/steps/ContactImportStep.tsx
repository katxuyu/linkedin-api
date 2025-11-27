'use client'

import React, { useState } from 'react'
import { useWizard } from '@/lib/context/WizardContext'
import { useImportSearchPreview } from '@/lib/hooks/useCampaigns'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ViewToggle } from '@/components/ui/view-toggle'
import { get_view_preference, save_view_preference } from '@/lib/utils/view-preferences'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Trash2, ExternalLink } from 'lucide-react'
import { TargetProfile } from '@/types'

interface ContactImportStepProps {
  on_next: () => void
  on_back: () => void
}

export const ContactImportStep: React.FC<ContactImportStepProps> = ({
  on_next,
}) => {
  const { state, update_state } = useWizard()
  const import_preview = useImportSearchPreview(state.clientAccessToken || '')
  
  const [active_tab, set_active_tab] = useState('manual')
  const [targets, set_targets] = useState<TargetProfile[]>([])
  const [view_mode, set_view_mode] = useState<'card' | 'list'>(() => get_view_preference('wizard-targets'))
  
  const [manual_url, set_manual_url] = useState('')
  const [manual_variables, set_manual_variables] = useState<Record<string, string>>({})
  
  const [search_url, set_search_url] = useState('')
  const [max_results, set_max_results] = useState(25)
  const [preview_data, set_preview_data] = useState<TargetProfile[]>([])
  const [csv_content, set_csv_content] = useState('')

  const handle_view_change = (mode: 'card' | 'list') => {
    set_view_mode(mode)
    save_view_preference('wizard-targets', mode)
  }

  const handle_add_manual_target = () => {
    if (!manual_url.trim()) {
      toast.error('Please enter a LinkedIn URL')
      return
    }

    const missing_vars = state.requiredVariables.filter(
      v => !manual_variables[v] || !manual_variables[v].trim()
    )

    if (missing_vars.length > 0) {
      toast.error(`Missing required variables: ${missing_vars.join(', ')}`)
      return
    }

    const new_target: TargetProfile = {
      url: manual_url,
      variables: { ...manual_variables },
    }

    set_targets([...targets, new_target])
    set_manual_url('')
    set_manual_variables({})
    toast.success('Target added')
  }

  const handle_remove_target = (index: number) => {
    set_targets(targets.filter((_, i) => i !== index))
  }

  const handle_parse_csv = () => {
    if (!csv_content.trim()) {
      toast.error('Please paste CSV content')
      return
    }

    try {
      const lines = csv_content.trim().split('\n')
      if (lines.length < 2) {
        toast.error('CSV must have a header row and at least one data row')
        return
      }

      const headers = lines[0].split(',').map(h => h.trim())
      const url_index = headers.findIndex(h => h.toLowerCase() === 'url')
      
      if (url_index === -1) {
        toast.error('CSV must have a "url" column')
        return
      }

      const variable_headers = headers.filter(h => h.toLowerCase() !== 'url')
      const parsed_targets: TargetProfile[] = []

      for (let i = 1; i < lines.length; i++) {
        const values = lines[i].split(',').map(v => v.trim())
        if (values.length !== headers.length) continue

        const url = values[url_index]
        const variables: Record<string, string> = {}

        variable_headers.forEach((header, idx) => {
          const actual_idx = headers.indexOf(header)
          if (actual_idx !== -1) {
            variables[header] = values[actual_idx]
          }
        })

        parsed_targets.push({ url, variables })
      }

      set_targets([...targets, ...parsed_targets])
      set_csv_content('')
      toast.success(`Added ${parsed_targets.length} targets from CSV`)
    } catch (error) {
      toast.error('Failed to parse CSV')
    }
  }

  const handle_preview_search = async () => {
    if (!search_url.trim()) {
      toast.error('Please enter a LinkedIn search URL')
      return
    }

    if (!state.outreachProfileId || !state.clientAccessToken) {
      toast.error('Missing profile or token')
      return
    }

    try {
      const result = await import_preview.mutateAsync({
        outreach_profile_id: state.outreachProfileId,
        search_url,
        max_results,
      })

      set_preview_data(result.targets)
      toast.success(`Found ${result.total} potential targets`)
    } catch (error: unknown) {
      const message =
        (error as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        (error instanceof Error ? error.message : 'Failed to preview search results')
      toast.error(message)
    }
  }

  const handle_import_search_results = () => {
    if (preview_data.length === 0) {
      toast.error('No preview data to import')
      return
    }

    update_state({
      importMethod: 'search',
      targetProfiles: preview_data,
    })

    toast.success(`Imported ${preview_data.length} targets from search`)
    on_next()
  }

  const handle_continue_with_manual = () => {
    if (targets.length === 0) {
      toast.error('Please add at least one target')
      return
    }

    update_state({
      importMethod: 'manual',
      targetProfiles: targets,
    })

    toast.success(`Added ${targets.length} manual targets`)
    on_next()
  }

  return (
    <div className="space-y-6">
      <Tabs value={active_tab} onValueChange={set_active_tab}>
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="manual">Manual Entry</TabsTrigger>
          <TabsTrigger value="search">LinkedIn Search</TabsTrigger>
        </TabsList>

        <TabsContent value="manual" className="space-y-4">
          <div className="space-y-4">
            <div>
              <Label htmlFor="manual-url">LinkedIn Profile URL</Label>
              <Input
                id="manual-url"
                value={manual_url}
                onChange={(e) => set_manual_url(e.target.value)}
                placeholder="https://www.linkedin.com/in/profile-name/"
              />
            </div>

            {state.requiredVariables.length > 0 && (
              <div className="grid grid-cols-2 gap-4">
                {state.requiredVariables.map((variable) => (
                  <div key={variable}>
                    <Label htmlFor={`var-${variable}`}>{variable}</Label>
                    <Input
                      id={`var-${variable}`}
                      value={manual_variables[variable] || ''}
                      onChange={(e) =>
                        set_manual_variables({
                          ...manual_variables,
                          [variable]: e.target.value,
                        })
                      }
                      placeholder={`Enter ${variable}`}
                    />
                  </div>
                ))}
              </div>
            )}

            <Button onClick={handle_add_manual_target}>
              Add Target
            </Button>

            <div className="border-t pt-4">
              <Label htmlFor="csv-import">Or Paste CSV</Label>
              <p className="text-sm text-gray-600 mb-2">
                Format: url,{state.requiredVariables.join(',')}
              </p>
              <Textarea
                id="csv-import"
                value={csv_content}
                onChange={(e) => set_csv_content(e.target.value)}
                placeholder="url,first_name,company&#10;https://linkedin.com/in/john,John,Acme Inc"
                rows={6}
              />
              <Button onClick={handle_parse_csv} className="mt-2">
                Parse CSV
              </Button>
            </div>

            {targets.length > 0 && (
              <div>
                <div className="flex justify-between items-center mb-4">
                  <h4 className="font-medium">Added Targets ({targets.length})</h4>
                  <div className="flex items-center gap-2">
                    <ViewToggle value={view_mode} onValueChange={handle_view_change} />
                    <Button onClick={handle_continue_with_manual}>
                      Continue with {targets.length} Targets
                    </Button>
                  </div>
                </div>
                <div className="border rounded-lg max-h-96 overflow-y-auto p-4">
                  {view_mode === 'card' ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                      {targets.map((target, index) => (
                        <Card key={index} className="relative">
                          <CardHeader className="pb-3">
                            <div className="flex items-start justify-between">
                              <CardTitle className="text-sm font-medium truncate pr-2">
                                <a
                                  href={target.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-blue-600 hover:underline flex items-center gap-1"
                                >
                                  <ExternalLink className="h-3 w-3" />
                                  Profile {index + 1}
                                </a>
                              </CardTitle>
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-6 w-6 p-0 text-red-600 hover:text-red-700"
                                onClick={() => handle_remove_target(index)}
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </div>
                          </CardHeader>
                          <CardContent className="pt-0">
                            <div className="space-y-2">
                              <div className="text-xs text-muted-foreground truncate">
                                {target.url}
                              </div>
                              {state.requiredVariables.length > 0 && (
                                <div className="flex flex-wrap gap-1">
                                  {state.requiredVariables.map((v) => (
                                    <Badge key={v} variant="outline" className="text-xs">
                                      {v}: {target.variables[v] || '-'}
                                    </Badge>
                                  ))}
                                </div>
                              )}
                            </div>
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>URL</TableHead>
                          {state.requiredVariables.map((v) => (
                            <TableHead key={v}>{v}</TableHead>
                          ))}
                          <TableHead>Actions</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {targets.map((target, index) => (
                          <TableRow key={index}>
                            <TableCell className="max-w-xs truncate">
                              {target.url}
                            </TableCell>
                            {state.requiredVariables.map((v) => (
                              <TableCell key={v}>{target.variables[v] || '-'}</TableCell>
                            ))}
                            <TableCell>
                              <Button
                                size="sm"
                                variant="destructive"
                                onClick={() => handle_remove_target(index)}
                              >
                                Remove
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </div>
              </div>
            )}
          </div>
        </TabsContent>

        <TabsContent value="search" className="space-y-4">
          <div className="space-y-4">
            <div>
              <Label htmlFor="search-url">LinkedIn Search URL</Label>
              <Input
                id="search-url"
                value={search_url}
                onChange={(e) => set_search_url(e.target.value)}
                placeholder="https://www.linkedin.com/search/results/people/?keywords=software%20engineer"
              />
              <p className="text-sm text-gray-600 mt-1">
                Copy the URL from your LinkedIn search results page
              </p>
            </div>

            <div>
              <Label htmlFor="max-results">Max Results</Label>
              <Input
                id="max-results"
                type="number"
                min="1"
                max="100"
                value={max_results}
                onChange={(e) => set_max_results(parseInt(e.target.value) || 25)}
              />
            </div>

            <Button
              onClick={handle_preview_search}
              disabled={import_preview.isPending}
            >
              {import_preview.isPending ? 'Loading Preview...' : 'Preview Results'}
            </Button>

            {preview_data.length > 0 && (
              <div>
                <div className="flex justify-between items-center mb-4">
                  <h4 className="font-medium">
                    Preview Results ({preview_data.length})
                  </h4>
                  <div className="flex items-center gap-2">
                    <ViewToggle value={view_mode} onValueChange={handle_view_change} />
                    <Button onClick={handle_import_search_results}>
                      Import {preview_data.length} Targets
                    </Button>
                  </div>
                </div>
                <div className="border rounded-lg max-h-96 overflow-y-auto p-4">
                  {view_mode === 'card' ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                      {preview_data.map((target, index) => (
                        <Card key={index}>
                          <CardHeader className="pb-3">
                            <CardTitle className="text-sm font-medium">
                              <a
                                href={target.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-blue-600 hover:underline flex items-center gap-1"
                              >
                                <ExternalLink className="h-3 w-3" />
                                Profile {index + 1}
                              </a>
                            </CardTitle>
                          </CardHeader>
                          <CardContent className="pt-0">
                            <div className="text-xs text-muted-foreground truncate">
                              {target.url}
                            </div>
                            {Object.keys(target.variables).length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-2">
                                {Object.entries(target.variables).map(([key, value]) => (
                                  <Badge key={key} variant="outline" className="text-xs">
                                    {key}: {value}
                                  </Badge>
                                ))}
                              </div>
                            )}
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>LinkedIn URL</TableHead>
                          {Object.keys(preview_data[0]?.variables || {}).length > 0 && (
                            Object.keys(preview_data[0].variables).map((key) => (
                              <TableHead key={key}>{key}</TableHead>
                            ))
                          )}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {preview_data.map((target, index) => (
                          <TableRow key={index}>
                            <TableCell className="max-w-xl truncate">
                              {target.url}
                            </TableCell>
                            {Object.keys(target.variables || {}).map((key) => (
                              <TableCell key={key}>{target.variables[key] || '-'}</TableCell>
                            ))}
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </div>
                <p className="text-sm text-gray-600 mt-2">
                  Note: Variables will be automatically extracted from profiles during import
                </p>
              </div>
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}


