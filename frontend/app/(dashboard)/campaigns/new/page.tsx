'use client'

import { WizardProvider } from '@/lib/context/WizardContext'
import { WizardContainer } from '@/components/wizard/WizardContainer'
import { ClientSelectionStep } from '@/components/wizard/steps/ClientSelectionStep'
import { LinkedInProfileStep } from '@/components/wizard/steps/LinkedInProfileStep'
import { CampaignTemplateStep } from '@/components/wizard/steps/CampaignTemplateStep'
import { ContactImportStep } from '@/components/wizard/steps/ContactImportStep'
import { ReviewLaunchStep } from '@/components/wizard/steps/ReviewLaunchStep'

const wizard_steps = [
  {
    title: 'Select Client',
    description: 'Choose the client for this campaign or create a new one',
    component: ClientSelectionStep,
  },
  {
    title: 'LinkedIn Profile',
    description: 'Select or add a LinkedIn outreach profile',
    component: LinkedInProfileStep,
  },
  {
    title: 'Campaign Template',
    description: 'Create a new campaign template or select an existing one',
    component: CampaignTemplateStep,
  },
  {
    title: 'Import Contacts',
    description: 'Add target contacts manually or import from LinkedIn search',
    component: ContactImportStep,
  },
  {
    title: 'Review & Launch',
    description: 'Review your campaign settings and launch',
    component: ReviewLaunchStep,
  },
]

export default function NewCampaignPage() {
  return (
    <WizardProvider>
      <div className="max-w-5xl mx-auto">
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-gray-900">Create New Campaign</h1>
          <p className="text-gray-600 mt-2">
            Follow the steps below to set up a new LinkedIn outreach campaign
          </p>
        </div>
        
        <WizardContainer steps={wizard_steps} />
      </div>
    </WizardProvider>
  )
}





