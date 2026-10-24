import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useSearchParams, Link } from 'react-router-dom';
import { MessageSquareText, Send, Loader2, Database, ChevronDown, Quote, Sparkles } from 'lucide-react';
import {
  fetchWorkflows,
  askData,
  fetchRagStatus,
  reindexWorkflow,
  type RagAnswer,
} from '../api/client';

interface WorkflowItem {
  id: string;
  query: string;
  status: string;
  created_at: string;
}

interface ChatTurn {
  question: string;
  answer?: RagAnswer;
  error?: string;
}

type IndexState = 'idle' | 'checking' | 'building' | 'ready' | 'failed';

const SUGGESTIONS = [
  'What are people most positive about?',
  'What are the top complaints?',
  'How does sentiment differ between sources?',
  'Summarise the most upvoted opinions.',
];

const SOURCE_STYLES: Record<string, string> = {
  youtube: 'bg-clay-coral/15 text-clay-coral-dark',
  amazon: 'bg-clay-yellow/25 text-clay-yellow-dark',
  reddit: 'bg-clay-blue/15 text-clay-blue-dark',
};

/** Renders [n] citation markers as small clay pills. */
const AnswerText = ({ text }: { text: string }) => (
  <p className="whitespace-pre-wrap leading-relaxed text-clay-ink">
    {text.split(/(\[\d+\])/g).map((part, i) =>
      /^\[\d+\]$/.test(part) ? (
        <sup key={i} className="mx-0.5 px-1.5 py-0.5 rounded-md bg-clay-purple/15 text-clay-purple-dark text-[10px] font-bold">
          {part.slice(1, -1)}
        </sup>
      ) : (
        <span key={i}>{part}</span>
      )
    )}
  </p>
);

export const AskAI = () => {
  const [params, setParams] = useSearchParams();
  const [workflows, setWorkflows] = useState<WorkflowItem[]>([]);
  const [loadingWorkflows, setLoadingWorkflows] = useState(true);

  const selectedId = params.get('workflow') || '';
  const selected = workflows.find((w) => w.id === selectedId);

  useEffect(() => {
    fetchWorkflows()
      .then((data) => {
        const done: WorkflowItem[] = (data.workflows || []).filter((w: WorkflowItem) =>
          ['completed', 'auto_approved'].includes(w.status)
        );
        setWorkflows(done);
        if (!selectedId && done.length > 0) {
          setParams({ workflow: done[0].id }, { replace: true });
        }
      })
      .catch((e) => console.error('Failed to load workflows', e))
      .finally(() => setLoadingWorkflows(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);


  if (!loadingWorkflows && workflows.length === 0) {
    return (
      <div className="space-y-6 animate-fade-in">
        <Heading />
        <div className="clay-card p-12 text-center">
          <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-clay-purple flex items-center justify-center shadow-[inset_0_2px_3px_rgba(255,255,255,0.3),0_4px_0_0_#7C3AED]">
            <Database className="w-8 h-8 text-white" />
          </div>
          <h3 className="text-xl font-bold text-clay-ink mb-2">No research to ask about yet</h3>
          <p className="text-clay-ink-muted mb-6">Run a workflow first. Its scraped data becomes the knowledge base for your questions.</p>
          <Link to="/app/workflows" className="clay-button inline-flex px-6 py-3">Start a workflow</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4">
        <Heading />
        <div className="relative w-full lg:w-80">
          <select
            value={selectedId}
            onChange={(e) => setParams({ workflow: e.target.value })}
            className="clay-input w-full appearance-none pr-10 font-medium cursor-pointer"
            aria-label="Workflow to ask about"
          >
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.query}
              </option>
            ))}
          </select>
          <ChevronDown className="w-4 h-4 absolute right-4 top-1/2 -translate-y-1/2 text-clay-ink-muted pointer-events-none" />
        </div>
      </div>

      {selectedId && <WorkflowChat key={selectedId} workflowId={selectedId} query={selected?.query} />}
    </div>
  );
};

/** Chat over one workflow. Keyed by workflow id, so switching resets it. */
const WorkflowChat = ({ workflowId, query }: { workflowId: string; query?: string }) => {
  const [indexState, setIndexState] = useState<IndexState>('checking');
  const [chunks, setChunks] = useState(0);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  // Make sure the selected workflow is queryable, rebuilding its index from
  // the database if the vector store was wiped (free hosts reset their disk).
  useEffect(() => {
    if (!workflowId) return;
    let cancelled = false;

    (async () => {
      try {
        const status = await fetchRagStatus(workflowId);
        if (cancelled) return;
        if (status.queryable) {
          setChunks(status.indexed_chunks);
          setIndexState('ready');
          return;
        }
        setIndexState('building');
        const built = await reindexWorkflow(workflowId);
        if (cancelled) return;
        setChunks(built.chunks || 0);
        setIndexState('ready');
      } catch (e) {
        if (!cancelled) {
          console.error('Indexing failed', e);
          setIndexState('failed');
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [workflowId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns]);

  const ask = async (text: string) => {
    const q = text.trim();
    if (!q || !workflowId || asking) return;
    setQuestion('');
    setAsking(true);
    setTurns((t) => [...t, { question: q }]);
    try {
      const answer = await askData(q, workflowId);
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, answer } : turn)));
    } catch (err) {
      const detail =
        (axios.isAxiosError(err) && err.response?.data?.detail) || 'Something went wrong. Try again.';
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, error: detail } : turn)));
    } finally {
      setAsking(false);
    }
  };

  return (
    <>
      <IndexBadge state={indexState} chunks={chunks} />

      <div className="clay-card p-4 md:p-6 min-h-[420px] flex flex-col">
        <div className="flex-1 space-y-6 overflow-y-auto">
          {turns.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center text-center py-10">
              <Sparkles className="w-10 h-10 text-clay-purple mb-3" />
              <p className="text-clay-ink font-semibold">
                Ask anything about {query ? <>"{query}"</> : 'this research'}
              </p>
              <p className="text-sm text-clay-ink-muted mt-1 mb-6">
                Answers come only from the collected data, with numbered citations.
              </p>
              <div className="flex flex-wrap justify-center gap-2 max-w-xl">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => ask(s)}
                    disabled={indexState !== 'ready'}
                    className="px-4 py-2 rounded-2xl text-sm bg-clay-bg border-2 border-clay-border text-clay-ink-light hover:border-clay-blue hover:text-clay-blue-dark transition-colors disabled:opacity-50"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((turn, i) => (
            <div key={i} className="space-y-3">
              <div className="flex justify-end">
                <div className="max-w-[85%] px-4 py-3 rounded-2xl rounded-br-md bg-clay-blue text-white shadow-[inset_0_2px_3px_rgba(255,255,255,0.3),0_3px_0_0_#2563EB]">
                  {turn.question}
                </div>
              </div>
              <div className="flex gap-3">
                <div className="w-9 h-9 shrink-0 rounded-xl bg-clay-purple flex items-center justify-center shadow-[inset_0_2px_3px_rgba(255,255,255,0.3),0_3px_0_0_#7C3AED]">
                  <MessageSquareText className="w-4 h-4 text-white" />
                </div>
                <div className="flex-1 min-w-0 space-y-3">
                  {!turn.answer && !turn.error && (
                    <div className="flex items-center gap-2 text-clay-ink-muted py-2">
                      <Loader2 className="w-4 h-4 animate-spin" /> Searching the collected data...
                    </div>
                  )}
                  {turn.error && <p className="text-clay-coral-dark">{turn.error}</p>}
                  {turn.answer && (
                    <>
                      <AnswerText text={turn.answer.answer} />
                      {turn.answer.confidence > 0 && (
                        <p className="text-xs text-clay-ink-muted">
                          Retrieval confidence {(turn.answer.confidence * 100).toFixed(0)}%
                        </p>
                      )}
                      {turn.answer.sources.length > 0 && (
                        <details className="group">
                          <summary className="cursor-pointer text-sm font-semibold text-clay-blue-dark list-none flex items-center gap-1">
                            <ChevronDown className="w-4 h-4 transition-transform group-open:rotate-180" />
                            {turn.answer.sources.length} sources
                          </summary>
                          <div className="grid sm:grid-cols-2 gap-3 mt-3">
                            {turn.answer.sources.map((s) => {
                              const src = String(s.metadata?.source || 'unknown').toLowerCase();
                              return (
                                <div key={s.id} className="p-3 rounded-2xl bg-clay-bg border-2 border-clay-border">
                                  <div className="flex items-center justify-between mb-2">
                                    <span className="text-xs font-bold text-clay-purple-dark">[{s.id}]</span>
                                    <span className="flex items-center gap-1">
                                      {s.metadata?.is_mock === true && (
                                        <span
                                          className="text-[11px] px-2 py-0.5 rounded-lg font-semibold bg-white text-clay-ink-muted border border-clay-border"
                                          title="Synthetic demo data, used when the live source was unavailable"
                                        >
                                          synthetic
                                        </span>
                                      )}
                                      <span className={`text-[11px] px-2 py-0.5 rounded-lg capitalize font-semibold ${SOURCE_STYLES[src] || 'bg-white text-clay-ink-light'}`}>
                                        {src}
                                      </span>
                                    </span>
                                  </div>
                                  <p className="text-xs text-clay-ink-light flex gap-1.5">
                                    <Quote className="w-3 h-3 shrink-0 mt-0.5 text-clay-ink-muted" />
                                    {s.text}
                                  </p>
                                </div>
                              );
                            })}
                          </div>
                        </details>
                      )}
                    </>
                  )}
                </div>
              </div>
            </div>
          ))}
          <div ref={endRef} />
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask(question);
          }}
          className="mt-6 flex gap-3"
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={indexState === 'ready' ? 'Ask a question about this research...' : 'Preparing knowledge base...'}
            disabled={indexState !== 'ready'}
            className="clay-input flex-1"
            maxLength={500}
          />
          <button
            type="submit"
            disabled={!question.trim() || asking || indexState !== 'ready'}
            className="clay-button px-5 flex items-center gap-2"
            aria-label="Ask"
          >
            {asking ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
            <span className="hidden sm:inline">Ask</span>
          </button>
        </form>
      </div>
    </>
  );
};

const Heading = () => (
  <div>
    <h1 className="text-3xl font-bold gradient-text">Ask AI</h1>
    <p className="text-clay-ink-muted mt-1">
      Retrieval-augmented answers grounded in each workflow's scraped data
    </p>
  </div>
);

const IndexBadge = ({ state, chunks }: { state: IndexState; chunks: number }) => {
  const content: Record<IndexState, { text: string; cls: string }> = {
    idle: { text: 'Pick a workflow', cls: 'bg-clay-bg text-clay-ink-muted' },
    checking: { text: 'Checking knowledge base...', cls: 'bg-clay-bg text-clay-ink-muted' },
    building: { text: 'Building knowledge base from collected data (one time)...', cls: 'bg-clay-yellow/20 text-clay-yellow-dark' },
    ready: { text: `Knowledge base ready · ${chunks} indexed chunks`, cls: 'bg-clay-green/15 text-clay-green-dark' },
    failed: {
      text: 'Could not build the knowledge base. The workflow may have no data, or the Gemini key is missing.',
      cls: 'bg-clay-coral/10 text-clay-coral-dark',
    },
  };
  const { text, cls } = content[state];
  return (
    <div className={`clay-badge ${cls}`}>
      {(state === 'checking' || state === 'building') && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
      {state === 'ready' && <Database className="w-3.5 h-3.5" />}
      {text}
    </div>
  );
};
