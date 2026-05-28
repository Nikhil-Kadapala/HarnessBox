import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"

interface AddRepoDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (repoUrl: string) => void
}

export function AddRepoDialog({ open, onOpenChange, onSubmit }: AddRepoDialogProps) {
  const [url, setUrl] = useState("")

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = url.trim()
    if (!trimmed) return
    onSubmit(trimmed)
    setUrl("")
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add Repository</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <label htmlFor="git-url" className="text-sm font-medium">
              Git URL
            </label>
            <Input
              id="git-url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://github.com/user/repo.git"
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={!url.trim()}>
              Add Repository
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
