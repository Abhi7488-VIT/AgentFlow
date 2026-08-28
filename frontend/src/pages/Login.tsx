import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Bot, LogIn, Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { login as apiLogin } from '../api/client';

export const Login = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();
  const { login } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const formData = new URLSearchParams();
      formData.append('username', email); // OAuth2 requires 'username'
      formData.append('password', password);

      const data = await apiLogin(formData);
      login(data.access_token, data.user);
      navigate('/');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to login');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-clay-bg text-clay-ink flex items-center justify-center p-4">
      <div className="clay-card max-w-md w-full p-8 animate-fade-in relative overflow-hidden">
        {/* Decorative blur */}
        <div className="absolute -top-24 -right-24 w-48 h-48 bg-clay-blue/20 rounded-full blur-[64px] pointer-events-none"></div>
        <div className="absolute -bottom-24 -left-24 w-48 h-48 bg-clay-purple/20 rounded-full blur-[64px] pointer-events-none"></div>

        <div className="relative z-10">
          <div className="flex flex-col items-center mb-8">
            <div className="w-16 h-16 rounded-2xl bg-clay-blue p-0.5 mb-4 shadow-[inset_0_2px_3px_rgba(255,255,255,0.3),0_4px_0_0_#2563EB]">
              <div className="w-full h-full bg-clay-blue-dark rounded-2xl flex items-center justify-center">
                <Bot className="w-8 h-8 text-white" />
              </div>
            </div>
            <h1 className="text-3xl font-bold text-clay-ink">Welcome Back</h1>
            <p className="text-clay-ink-muted mt-2">Log in to your AgentFlow workspace</p>
          </div>

          {error && (
            <div className="bg-clay-coral/10 border-2 border-clay-coral/20 text-clay-coral-dark p-3 rounded-xl mb-6 text-sm text-center">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-clay-ink-light mb-1">Email Address</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full clay-input"
                placeholder="admin@agentflow.ai"
                required
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-clay-ink-light mb-1">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full clay-input"
                placeholder="••••••••"
                required
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full clay-button py-3 flex items-center justify-center gap-2 mt-6"
            >
              {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <LogIn className="w-5 h-5" />}
              {loading ? 'Authenticating...' : 'Sign In'}
            </button>
          </form>

          <p className="text-center text-clay-ink-muted mt-6 text-sm">
            Don't have an account?{' '}
            <Link to="/signup" className="text-clay-blue hover:text-clay-blue-dark transition-colors">
              Create workspace
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
};
