'use client'

import { LayoutGrid, List } from 'lucide-react'
import { Button } from '@/components/ui/button'

type ViewMode = 'card' | 'list'

interface ViewToggleProps {
  value: ViewMode
  onValueChange: (value: ViewMode) => void
}

export const ViewToggle: React.FC<ViewToggleProps> = ({ value, onValueChange }) => {
  return (
    <div className="flex items-center gap-1 border rounded-md p-1">
      <Button
        variant={value === 'card' ? 'secondary' : 'ghost'}
        size="sm"
        onClick={() => onValueChange('card')}
        className="h-8 px-3"
        aria-label="Card view"
      >
        <LayoutGrid className="h-4 w-4" />
      </Button>
      <Button
        variant={value === 'list' ? 'secondary' : 'ghost'}
        size="sm"
        onClick={() => onValueChange('list')}
        className="h-8 px-3"
        aria-label="List view"
      >
        <List className="h-4 w-4" />
      </Button>
    </div>
  )
}

