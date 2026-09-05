import { useState, useEffect } from 'react';
import { Workflow, FileText, Activity, PieChart } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart as RechartsPie, Pie, Cell } from 'recharts';
import { MetricCard } from '../components/dashboard/MetricCard';
import { fetchOverview, fetchSentiment, fetchTrends, fetchRecentActivity } from '../api/client';

const COLOR_MAP: Record<string, string> = {
  'POSITIVE': '#10b981',
  'NEGATIVE': '#ef4444',
  'NEUTRAL': '#6b7280',
  'Positive': '#10b981',
  'Negative': '#ef4444',
  'Neutral': '#6b7280'
};

// Sentiment is VADER's compound score in [-1, 1]: -1 wholly negative,
// 0 neutral, +1 wholly positive. Rendering it as a percentage would imply
// a 0-100 scale it does not have.
const formatSentiment = (score?: number) => {
  if (score === undefined || score === null || Number.isNaN(score)) return '—';
  const rounded = score.toFixed(2);
  return score > 0 ? `+${rounded}` : rounded;
};

export const Dashboard = () => {
  const [metrics, setMetrics] = useState<any>(null);
  const [sentimentData, setSentimentData] = useState<any[]>([]);
  const [trendData, setTrendData] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadDashboard = async () => {
      try {
        const [overviewRes, sentimentRes, trendsRes] =
          await Promise.allSettled([
            fetchOverview(),
            fetchSentiment(),
            fetchTrends(),
            fetchRecentActivity(),
          ]);

        // Metrics
        if (overviewRes.status === 'fulfilled') {
          setMetrics(overviewRes.value);
        } else {
          console.warn('fetchOverview failed, using fallback:', overviewRes.reason);
          setMetrics({ total_workflows: 0, total_reports: 0, avg_sentiment_score: 0, total_data_points: 0 });
        }

        // Sentiment distribution
        if (sentimentRes.status === 'fulfilled') {
          setSentimentData(Array.isArray(sentimentRes.value) ? sentimentRes.value : []);
        } else {
          console.warn('fetchSentiment failed, using fallback:', sentimentRes.reason);
          setSentimentData([
            { label: 'Positive', count: 0 },
            { label: 'Negative', count: 0 },
            { label: 'Neutral', count: 0 },
          ]);
        }

        // Trend data
        if (trendsRes.status === 'fulfilled') {
          setTrendData(Array.isArray(trendsRes.value) ? trendsRes.value : []);
        } else {
          console.warn('fetchTrends failed, using fallback:', trendsRes.reason);
          setTrendData([]);
        }

        // Recent activity removed
      } finally {
        setLoading(false);
      }
    };

    loadDashboard();
  }, []);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="flex items-center gap-3 text-clay-blue">
          <div className="w-4 h-4 rounded-full bg-clay-blue animate-ping"></div>
          <span className="text-xl font-medium text-clay-ink">Loading AI Insights...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold gradient-text">Market Intelligence Overview</h1>
          <p className="text-clay-ink-muted mt-1 text-sm md:text-base">Real-time analysis from your active workflows</p>
        </div>
        <button className="clay-button px-4 py-2 text-sm md:px-6 md:text-base flex items-center gap-2 w-full sm:w-auto justify-center">
          <Activity className="w-4 h-4 md:w-5 md:h-5" />
          Live Tracking Active
        </button>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard 
          title="Total Workflows" 
          value={metrics?.total_workflows || 0} 
          icon={<Workflow className="w-6 h-6" />}
        />
        <MetricCard 
          title="Reports Generated" 
          value={metrics?.total_reports || 0} 
          icon={<FileText className="w-6 h-6" />}
        />
        <MetricCard 
          title="Avg Sentiment" 
          value={formatSentiment(metrics?.avg_sentiment_score)} 
          icon={<PieChart className="w-6 h-6" />}
        />
        <MetricCard 
          title="Data Points Scraped" 
          value={metrics?.total_data_points || 0} 
          icon={<Activity className="w-6 h-6" />}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Trend Chart */}
        <div className="clay-card p-6 lg:col-span-2">
          <h2 className="text-xl font-bold mb-6 text-clay-ink">Sentiment Trends</h2>
          <div className="h-80 min-w-0">
            <ResponsiveContainer width="99%" height="100%">
              <AreaChart data={trendData}>
                <defs>
                  <linearGradient id="colorPositive" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="colorNegative" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" vertical={false} />
                <XAxis dataKey="date" stroke="#9CA3AF" axisLine={false} tickLine={false} />
                <YAxis stroke="#9CA3AF" axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#FFFFFF', borderColor: '#E5E7EB', borderRadius: '16px', boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}
                  itemStyle={{ color: '#1E1B4B' }}
                />
                <Area type="monotone" dataKey="positive" stroke="#10b981" fillOpacity={1} fill="url(#colorPositive)" strokeWidth={2} />
                <Area type="monotone" dataKey="negative" stroke="#ef4444" fillOpacity={1} fill="url(#colorNegative)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Sentiment Distribution */}
        <div className="clay-card p-6">
          <h2 className="text-xl font-bold mb-6 text-clay-ink">Overall Sentiment</h2>
          <div className="h-64 min-w-0">
            <ResponsiveContainer width="99%" height="100%">
              <RechartsPie>
                <Pie
                  data={sentimentData}
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={5}
                  dataKey="count"
                  nameKey="label"
                >
                  {sentimentData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLOR_MAP[entry.label] || '#9ca3af'} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ backgroundColor: '#FFFFFF', borderColor: '#E5E7EB', borderRadius: '16px', boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}
                />
              </RechartsPie>
            </ResponsiveContainer>
          </div>
          <div className="flex justify-center gap-4 mt-4">
            {sentimentData.map((entry) => (
              <div key={entry.label} className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: COLOR_MAP[entry.label] || '#9ca3af' }}></div>
                <span className="text-sm text-clay-ink-light">{entry.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
