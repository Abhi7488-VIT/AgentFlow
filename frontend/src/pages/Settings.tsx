import { useEffect, useState } from 'react';
import { User, Shield, Server, Database, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { fetchHealth } from '../api/client';

type Health = { status: string; database?: string } | null;

export const Settings = () => {
  const { user, isDemo } = useAuth();
  const [health, setHealth] = useState<Health>(null);
  const [healthError, setHealthError] = useState(false);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch(() => setHealthError(true));
  }, []);

  const apiOk = healthError ? false : health ? health.status === 'ok' : null;
  const dbOk = healthError ? false : health ? health.database === 'ok' : null;

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-3xl font-bold gradient-text">Settings</h1>
        <p className="text-clay-ink-muted mt-1">Your account and system status</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="clay-card p-6 space-y-4">
          <h2 className="text-lg font-bold text-clay-ink flex items-center gap-2">
            <User className="w-5 h-5 text-clay-blue" /> Account
          </h2>
          <dl className="space-y-3 text-sm">
            <Row label="Name" value={user?.full_name || '—'} />
            <Row label="Email" value={user?.email || '—'} />
            <Row
              label="Role"
              value={
                <span className="inline-flex items-center gap-1 capitalize">
                  <Shield className="w-4 h-4 text-clay-purple" /> {isDemo ? 'Demo visitor' : user?.role}
                </span>
              }
            />
          </dl>
        </div>

        <div className="clay-card p-6 space-y-4">
          <h2 className="text-lg font-bold text-clay-ink flex items-center gap-2">
            <Server className="w-5 h-5 text-clay-blue" /> System status
          </h2>
          <ul className="space-y-3 text-sm">
            <li className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-clay-ink-light"><Server className="w-4 h-4" /> API server</span>
              <Status ok={apiOk} />
            </li>
            <li className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-clay-ink-light"><Database className="w-4 h-4" /> Database</span>
              <Status ok={dbOk} />
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
};

const Status = ({ ok }: { ok: boolean | null }) =>
  ok === null ? (
    <Loader2 className="w-5 h-5 animate-spin text-clay-ink-muted" />
  ) : ok ? (
    <CheckCircle className="w-5 h-5 text-clay-green-dark" />
  ) : (
    <XCircle className="w-5 h-5 text-clay-coral" />
  );

const Row = ({ label, value }: { label: string; value: React.ReactNode }) => (
  <div className="flex items-center justify-between gap-4">
    <dt className="text-clay-ink-muted">{label}</dt>
    <dd className="font-medium text-clay-ink truncate">{value}</dd>
  </div>
);
