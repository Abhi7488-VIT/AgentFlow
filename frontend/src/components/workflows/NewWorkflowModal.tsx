import { useState } from 'react';
import { X } from 'lucide-react';
import { createWorkflow } from '../../api/client';

export const NewWorkflowModal = ({ onClose, onSuccess }: { onClose: () => void, onSuccess: () => void }) => {
  const [query, setQuery] = useState('');
  const [sources, setSources] = useState({ amazon: true, youtube: true, reddit: true });
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    
    const activeSources = Object.entries(sources)
      .filter(([_, isActive]) => isActive)
      .map(([key]) => key);

    try {
      await createWorkflow({ query, sources: activeSources });
      onSuccess();
    } catch (error) {
      console.error("Failed to create workflow", error);
      alert("Failed to create workflow. Check console.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 animate-fade-in">
      <div className="clay-card w-full max-w-lg p-6 animate-slide-up relative">
        <button onClick={onClose} className="absolute top-4 right-4 text-clay-ink-muted hover:text-clay-ink">
          <X className="w-6 h-6" />
        </button>

        <h2 className="text-2xl font-bold mb-6 text-clay-ink">New Research Workflow</h2>

        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label className="block text-sm font-medium text-clay-ink-light mb-2">
              Research Query
            </label>
            <input
              type="text"
              required
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g., iPhone 17 battery life user sentiment"
              className="w-full clay-input"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-clay-ink-light mb-2">
              Data Sources
            </label>
            <div className="flex gap-4">
              {['amazon', 'youtube', 'reddit'].map((source) => (
                <label key={source} className="flex items-center gap-2 cursor-pointer">
                  <input 
                    type="checkbox" 
                    checked={sources[source as keyof typeof sources]}
                    onChange={(e) => setSources({...sources, [source]: e.target.checked})}
                    className="rounded border-clay-border bg-white text-clay-blue focus:ring-clay-blue accent-clay-blue w-5 h-5"
                  />
                  <span className="capitalize text-clay-ink">{source}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="pt-4 flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="clay-button-ghost px-6 py-2"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !query}
              className="clay-button px-6 py-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? 'Starting Agents...' : 'Launch Agents'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
