import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Bot, Sparkles, ArrowRight, Loader2, Search, Filter, Brain, Lightbulb, FileText,
  ShieldCheck, Check, MessageSquareText, ShoppingCart, MessagesSquare,
  CalendarClock, Download, Activity, Menu, X, CirclePlay,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useDemoLogin } from '../hooks/useDemoLogin';

/** GitHub mark; lucide dropped brand icons in v1. */
const GithubIcon = ({ className = "" }: { className?: string }) => (
  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={className}>
    <path d="M12 .5C5.65.5.5 5.65.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.78 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.42-2.7 5.4-5.26 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z" />
  </svg>
);

const REPO_URL = 'https://github.com/AdityaRai123/AgentFlow';

const AGENTS = [
  { icon: Search, name: 'Research', desc: 'Collects live comments and reviews from YouTube, Amazon and Reddit.', color: 'bg-clay-blue', shadow: '#2563EB' },
  { icon: Filter, name: 'Cleaning', desc: 'Deduplicates, normalises text and filters out other languages.', color: 'bg-clay-green', shadow: '#059669' },
  { icon: Brain, name: 'NLP', desc: 'Scores sentiment with VADER and pulls keywords and trends with TF-IDF.', color: 'bg-clay-purple', shadow: '#7C3AED' },
  { icon: Lightbulb, name: 'Insight', desc: 'Gemini extracts pain points, competitors and opportunities.', color: 'bg-clay-yellow', shadow: '#D97706' },
  { icon: FileText, name: 'Report', desc: 'Writes an executive report with findings and recommendations.', color: 'bg-clay-coral', shadow: '#E11D48' },
  { icon: ShieldCheck, name: 'Reviewer', desc: 'Checks quality and sends weak drafts back for revision.', color: 'bg-clay-blue', shadow: '#2563EB' },
];

const FEATURES = [
  { icon: Activity, title: 'Live web data', desc: 'Real comments and reviews, collected at run time, not a canned dataset.' },
  { icon: MessageSquareText, title: 'Ask AI with citations', desc: 'Chat with each workflow\'s data. Every answer cites the comments it came from.' },
  { icon: Brain, title: 'Real NLP pipeline', desc: 'Lexicon sentiment, TF-IDF keywords and trend detection before any LLM is involved.' },
  { icon: CalendarClock, title: 'Scheduled runs', desc: 'Re-run research on a schedule to track how opinion shifts over time.' },
  { icon: Download, title: 'PDF & DOCX export', desc: 'Download polished reports to share with your team.' },
  { icon: ShieldCheck, title: 'Self-reviewing output', desc: 'A reviewer agent loops weak reports back before you ever see them.' },
];

const STACK = ['React', 'TypeScript', 'Tailwind', 'FastAPI', 'LangGraph', 'Gemini', 'ChromaDB', 'PostgreSQL', 'Docker', 'Prometheus', 'MLflow'];

/** Hero visual: the agent pipeline ticking through its stages. */
const PipelinePreview = () => {
  const [step, setStep] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setStep((s) => (s + 1) % (AGENTS.length + 2)), 1100);
    return () => clearInterval(id);
  }, []);

  const finished = step >= AGENTS.length;

  return (
    <div className="clay-card p-5 md:p-6 w-full max-w-md mx-auto relative">
      <div className="absolute -top-10 -right-10 w-40 h-40 bg-clay-purple/25 rounded-full blur-[60px] pointer-events-none" />
      <div className="relative">
        <div className="flex items-center justify-between mb-4">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wider text-clay-ink-muted">Workflow</p>
            <p className="font-bold text-clay-ink truncate">"iPhone 16 battery life"</p>
          </div>
          <span className={`clay-badge shrink-0 ${finished ? 'bg-clay-green/15 text-clay-green-dark' : 'bg-clay-blue/15 text-clay-blue-dark'}`}>
            {finished ? <Check className="w-3.5 h-3.5" /> : <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {finished ? 'Report ready' : 'Running'}
          </span>
        </div>

        <ul className="space-y-2">
          {AGENTS.map((a, i) => {
            const state = i < step ? 'done' : i === step ? 'active' : 'queued';
            return (
              <li
                key={a.name}
                className={`flex items-center gap-3 px-3 py-2 rounded-2xl transition-all duration-300 ${state === 'active' ? 'bg-clay-blue/10 scale-[1.02]' : ''}`}
              >
                <span
                  className={`w-8 h-8 rounded-xl flex items-center justify-center transition-all ${state === 'queued' ? 'bg-clay-bg' : a.color}`}
                  style={state === 'queued' ? undefined : { boxShadow: `inset 0 2px 3px rgba(255,255,255,0.3), 0 3px 0 0 ${a.shadow}` }}
                >
                  <a.icon className={`w-4 h-4 ${state === 'queued' ? 'text-clay-ink-muted' : 'text-white'}`} />
                </span>
                <span className={`flex-1 text-sm font-semibold ${state === 'queued' ? 'text-clay-ink-muted' : 'text-clay-ink'}`}>{a.name} agent</span>
                {state === 'done' && <Check className="w-4 h-4 text-clay-green-dark" />}
                {state === 'active' && <Loader2 className="w-4 h-4 text-clay-blue animate-spin" />}
              </li>
            );
          })}
        </ul>

        <div className={`mt-4 p-4 rounded-2xl bg-clay-bg border-2 border-clay-border transition-opacity duration-500 ${finished ? 'opacity-100' : 'opacity-40'}`}>
          <p className="text-xs font-semibold uppercase tracking-wider text-clay-ink-muted mb-3">Sentiment</p>
          {[
            { label: 'Positive', w: '58%', c: 'bg-clay-green' },
            { label: 'Neutral', w: '27%', c: 'bg-clay-ink-muted' },
            { label: 'Negative', w: '15%', c: 'bg-clay-coral' },
          ].map((b) => (
            <div key={b.label} className="flex items-center gap-3 mb-2 last:mb-0">
              <span className="w-16 text-xs text-clay-ink-light">{b.label}</span>
              <div className="flex-1 h-2.5 rounded-full bg-white overflow-hidden">
                <div className={`h-full rounded-full ${b.c} transition-all duration-700`} style={{ width: finished ? b.w : '0%' }} />
              </div>
            </div>
          ))}
          <p className="text-[11px] text-clay-ink-muted mt-3">Illustration. The demo runs on real data.</p>
        </div>
      </div>
    </div>
  );
};

interface DemoButtonProps {
  isAuthenticated: boolean;
  loading: boolean;
  onStart: () => void;
  className?: string;
}

/** Primary CTA: opens the dashboard when signed in, the demo otherwise. */
const DemoButton = ({ isAuthenticated, loading, onStart, className = '' }: DemoButtonProps) =>
  isAuthenticated ? (
    <Link to="/app" className={`clay-button px-6 py-3 inline-flex items-center justify-center gap-2 ${className}`}>
      Open dashboard <ArrowRight className="w-5 h-5" />
    </Link>
  ) : (
    <button onClick={onStart} disabled={loading} className={`clay-button px-6 py-3 inline-flex items-center justify-center gap-2 ${className}`}>
      {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Sparkles className="w-5 h-5" />}
      {loading ? 'Opening demo...' : 'Try the live demo'}
    </button>
  );

export const Landing = () => {
  const { isAuthenticated } = useAuth();
  const demo = useDemoLogin();
  const [menuOpen, setMenuOpen] = useState(false);
  const demoProps = { isAuthenticated, loading: demo.loading, onStart: demo.start };

  const navLinks = [
    { href: '#how', label: 'How it works' },
    { href: '#ask', label: 'Ask AI' },
    { href: '#features', label: 'Features' },
  ];

  return (
    <div className="min-h-screen bg-clay-bg text-clay-ink overflow-x-hidden">
      {/* Nav */}
      <header className="sticky top-0 z-30 bg-clay-bg/80 backdrop-blur-md border-b-2 border-clay-border/60">
        <nav className="max-w-6xl mx-auto px-4 md:px-6 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2">
            <Bot className="w-7 h-7 text-clay-blue" />
            <span className="text-lg font-bold gradient-text">AgentFlow</span>
          </Link>
          <div className="hidden md:flex items-center gap-8 text-sm font-medium text-clay-ink-light">
            {navLinks.map((l) => <a key={l.href} href={l.href} className="hover:text-clay-ink transition-colors">{l.label}</a>)}
          </div>
          <div className="hidden md:flex items-center gap-3">
            {!isAuthenticated && <Link to="/login" className="clay-button-ghost px-4 py-2 text-sm">Sign in</Link>}
            <DemoButton {...demoProps} className="!px-4 !py-2 text-sm" />
          </div>
          <button className="md:hidden p-2 text-clay-ink-light" onClick={() => setMenuOpen((o) => !o)} aria-label="Menu">
            {menuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </nav>
        {menuOpen && (
          <div className="md:hidden px-4 pb-4 space-y-2 animate-fade-in">
            {navLinks.map((l) => (
              <a key={l.href} href={l.href} onClick={() => setMenuOpen(false)} className="block px-3 py-2 rounded-xl text-clay-ink-light hover:bg-white">{l.label}</a>
            ))}
            {!isAuthenticated && <Link to="/login" className="block px-3 py-2 rounded-xl text-clay-ink-light hover:bg-white">Sign in</Link>}
          </div>
        )}
      </header>

      {/* Hero */}
      <section className="max-w-6xl mx-auto px-4 md:px-6 pt-12 md:pt-20 pb-16 grid lg:grid-cols-2 gap-12 items-center">
        <div className="animate-slide-up">
          <span className="clay-badge bg-white text-clay-purple-dark border-2 border-clay-border mb-6">
            <Sparkles className="w-3.5 h-3.5" /> 6 AI agents · live web data
          </span>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold leading-[1.05] tracking-tight">
            Market research that <span className="gradient-text">runs itself.</span>
          </h1>
          <p className="mt-6 text-lg text-clay-ink-light max-w-xl">
            Type a product or topic. A team of AI agents gathers what people are saying on YouTube,
            Amazon and Reddit, analyses the sentiment, and writes you an executive report you can question.
          </p>
          <div className="mt-8 flex flex-col sm:flex-row gap-3">
            <DemoButton {...demoProps} />
            {!isAuthenticated && (
              <Link to="/signup" className="clay-button-ghost bg-white px-6 py-3 inline-flex items-center justify-center gap-2">
                Create free account
              </Link>
            )}
          </div>
          {demo.error ? (
            <p className="mt-3 text-sm text-clay-coral-dark">{demo.error}</p>
          ) : (
            !isAuthenticated && <p className="mt-3 text-sm text-clay-ink-muted">No signup needed for the demo.</p>
          )}
        </div>
        <div className="animate-clay-bounce delay-200 opacity-0">
          <PipelinePreview />
        </div>
      </section>

      {/* Highlights */}
      <section className="max-w-6xl mx-auto px-4 md:px-6 pb-20 grid grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6">
        {[
          { cls: 'clay-card-blue', big: '6', small: 'specialised agents' },
          { cls: 'clay-card-green', big: '3', small: 'live data sources' },
          { cls: 'clay-card-purple', big: 'RAG', small: 'answers with citations' },
          { cls: 'clay-card-coral', big: 'PDF', small: '& DOCX report export' },
        ].map((s) => (
          <div key={s.small} className={`${s.cls} p-5 md:p-6`}>
            <p className="text-3xl md:text-4xl font-extrabold">{s.big}</p>
            <p className="text-sm md:text-base font-medium opacity-90 mt-1">{s.small}</p>
          </div>
        ))}
      </section>

      {/* How it works */}
      <section id="how" className="max-w-6xl mx-auto px-4 md:px-6 pb-24 scroll-mt-20">
        <div className="text-center max-w-2xl mx-auto mb-12">
          <p className="text-sm font-bold uppercase tracking-wider text-clay-blue-dark">How it works</p>
          <h2 className="text-3xl md:text-4xl font-extrabold mt-2">One query. Six agents. One report.</h2>
          <p className="text-clay-ink-light mt-4">
            Agents are wired together as a LangGraph state machine. Each one hands its output to the next,
            and the reviewer can send a weak draft back for another pass.
          </p>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {AGENTS.map((a, i) => (
            <div key={a.name} className="clay-card p-6 hover:-translate-y-1 transition-transform duration-200">
              <div className="flex items-center justify-between mb-4">
                <span
                  className={`w-12 h-12 rounded-2xl ${a.color} flex items-center justify-center`}
                  style={{ boxShadow: `inset 0 2px 3px rgba(255,255,255,0.3), 0 4px 0 0 ${a.shadow}` }}
                >
                  <a.icon className="w-6 h-6 text-white" />
                </span>
                <span className="text-4xl font-extrabold text-clay-border">0{i + 1}</span>
              </div>
              <h3 className="text-lg font-bold">{a.name} agent</h3>
              <p className="text-clay-ink-light mt-2 text-sm leading-relaxed">{a.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Ask AI */}
      <section id="ask" className="max-w-6xl mx-auto px-4 md:px-6 pb-24 grid lg:grid-cols-2 gap-12 items-center scroll-mt-20">
        <div>
          <p className="text-sm font-bold uppercase tracking-wider text-clay-purple-dark">Ask AI</p>
          <h2 className="text-3xl md:text-4xl font-extrabold mt-2">Question the data, not just the summary.</h2>
          <p className="text-clay-ink-light mt-4">
            Every completed workflow is embedded into its own vector collection. Ask follow-up questions and
            get answers built only from the comments that were collected, each one cited so you can check it.
          </p>
          <ul className="mt-6 space-y-3">
            {['Retrieval-augmented generation over ChromaDB', 'Answers cite the exact source comments', 'Says so when the data does not cover a question'].map((t) => (
              <li key={t} className="flex items-center gap-3 text-clay-ink-light">
                <span className="w-6 h-6 rounded-lg bg-clay-green/20 flex items-center justify-center"><Check className="w-4 h-4 text-clay-green-dark" /></span>
                {t}
              </li>
            ))}
          </ul>
        </div>
        <div className="clay-card p-5 md:p-6 space-y-4">
          <div className="flex justify-end">
            <div className="max-w-[85%] px-4 py-3 rounded-2xl rounded-br-md bg-clay-blue text-white shadow-[inset_0_2px_3px_rgba(255,255,255,0.3),0_3px_0_0_#2563EB]">
              What do people complain about most?
            </div>
          </div>
          <div className="flex gap-3">
            <span className="w-9 h-9 shrink-0 rounded-xl bg-clay-purple flex items-center justify-center shadow-[inset_0_2px_3px_rgba(255,255,255,0.3),0_3px_0_0_#7C3AED]">
              <MessageSquareText className="w-4 h-4 text-white" />
            </span>
            <div className="text-sm text-clay-ink leading-relaxed">
              The most common complaint is battery drain during gaming and video calls
              <sup className="mx-0.5 px-1.5 py-0.5 rounded-md bg-clay-purple/15 text-clay-purple-dark text-[10px] font-bold">2</sup>
              <sup className="mx-0.5 px-1.5 py-0.5 rounded-md bg-clay-purple/15 text-clay-purple-dark text-[10px] font-bold">5</sup>,
              followed by slow charging compared with competitors
              <sup className="mx-0.5 px-1.5 py-0.5 rounded-md bg-clay-purple/15 text-clay-purple-dark text-[10px] font-bold">7</sup>.
              <div className="mt-3 flex flex-wrap gap-2">
                <span className="clay-badge bg-clay-coral/15 text-clay-coral-dark"><CirclePlay className="w-3.5 h-3.5" /> YouTube</span>
                <span className="clay-badge bg-clay-yellow/25 text-clay-yellow-dark"><ShoppingCart className="w-3.5 h-3.5" /> Amazon</span>
              </div>
              <p className="text-[11px] text-clay-ink-muted mt-3">Example answer</p>
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="max-w-6xl mx-auto px-4 md:px-6 pb-24 scroll-mt-20">
        <div className="text-center max-w-2xl mx-auto mb-12">
          <p className="text-sm font-bold uppercase tracking-wider text-clay-green-dark">Features</p>
          <h2 className="text-3xl md:text-4xl font-extrabold mt-2">Built like a real product</h2>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {FEATURES.map((f) => (
            <div key={f.title} className="clay-card p-6">
              <f.icon className="w-7 h-7 text-clay-blue mb-4" />
              <h3 className="font-bold text-lg">{f.title}</h3>
              <p className="text-sm text-clay-ink-light mt-2 leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-wrap justify-center gap-3">
          {[{ icon: CirclePlay, label: 'YouTube' }, { icon: ShoppingCart, label: 'Amazon' }, { icon: MessagesSquare, label: 'Reddit' }].map((s) => (
            <span key={s.label} className="clay-badge bg-white text-clay-ink border-2 border-clay-border !px-4 !py-2 !text-sm">
              <s.icon className="w-4 h-4 text-clay-blue" /> {s.label}
            </span>
          ))}
        </div>
      </section>

      {/* Stack */}
      <section className="max-w-6xl mx-auto px-4 md:px-6 pb-24 text-center">
        <p className="text-sm font-bold uppercase tracking-wider text-clay-ink-muted mb-6">Built with</p>
        <div className="flex flex-wrap justify-center gap-2 md:gap-3">
          {STACK.map((t) => (
            <span key={t} className="px-4 py-2 rounded-2xl bg-white border-2 border-clay-border text-sm font-semibold text-clay-ink-light">{t}</span>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="max-w-6xl mx-auto px-4 md:px-6 pb-20">
        <div className="clay-card-blue p-8 md:p-12 text-center relative overflow-hidden">
          <div className="absolute -bottom-16 -left-16 w-56 h-56 bg-white/15 rounded-full blur-2xl pointer-events-none" />
          <h2 className="text-3xl md:text-4xl font-extrabold relative">See it run on real data</h2>
          <p className="mt-3 text-white/90 max-w-xl mx-auto relative">
            Open the demo workspace, start a workflow on any product, and watch the agents work.
          </p>
          <div className="mt-8 relative">
            {isAuthenticated ? (
              <Link to="/app" className="inline-flex items-center gap-2 px-6 py-3 rounded-2xl bg-white text-clay-blue-dark font-bold shadow-[0_5px_0_0_#1D4ED8] hover:-translate-y-0.5 transition-transform">
                Open dashboard <ArrowRight className="w-5 h-5" />
              </Link>
            ) : (
              <button onClick={demo.start} disabled={demo.loading} className="inline-flex items-center gap-2 px-6 py-3 rounded-2xl bg-white text-clay-blue-dark font-bold shadow-[0_5px_0_0_#1D4ED8] hover:-translate-y-0.5 transition-transform disabled:opacity-70">
                {demo.loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Sparkles className="w-5 h-5" />}
                {demo.loading ? 'Opening demo...' : 'Try the live demo'}
              </button>
            )}
          </div>
        </div>
      </section>

      <footer className="border-t-2 border-clay-border">
        <div className="max-w-6xl mx-auto px-4 md:px-6 py-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-clay-ink-muted">
          <div className="flex items-center gap-2">
            <Bot className="w-5 h-5 text-clay-blue" />
            <span className="font-semibold text-clay-ink">AgentFlow</span>
            <span>· multi-agent market intelligence</span>
          </div>
          <a href={REPO_URL} target="_blank" rel="noreferrer" className="flex items-center gap-2 hover:text-clay-ink transition-colors">
            <GithubIcon className="w-4 h-4" /> Source on GitHub
          </a>
        </div>
      </footer>
    </div>
  );
};
