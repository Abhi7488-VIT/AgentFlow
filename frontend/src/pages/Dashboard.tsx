import { useState, useEffect } from 'react';
import { Workflow, FileText, Activity, PieChart } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart as RechartsPie, Pie, Cell } from 'recharts';
import { MetricCard } from '../components/dashboard/MetricCard';
import { fetchOverview, fetchSentiment, fetchTrends, fetchRecentActivity } from '../api/client';

const COLORS = ['#10b981', '#ef4444', '#6b7280']; // Positive, Negative, Neutral

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
          setMetrics({ total_workflows: 0, total_reports: 0, avg_sentiment_score: 0.5, total_data_points: 0 });
        }

        // Sentiment distribution
        if (sentimentRes.status === 'fulfilled') {
          setSentimentData(sentimentRes.value);
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
          setTrendData(trendsRes.value);
        } else {
          console.warn('fetchTrends failed, using fallback:', trendsRes.reason);
          setTrendData([
            { date: 'Mon', positive: 0, negative: 0 },
            { date: 'Tue', positive: 0, negative: 0 },
            { date: 'Wed', positive: 0, negative: 0 },
            { date: 'Thu', positive: 0, negative: 0 },
            { date: 'Fri', positive: 0, negative: 0 },
            { date: 'Sat', positive: 0, negative: 0 },
            { date: 'Sun', positive: 0, negative: 0 },
          ]);
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
        <div className="flex items-center gap-3 text-electric-blue">
          <div className="w-4 h-4 rounded-full bg-blue-500 animate-ping"></div>
          <span className="text-xl font-medium">Loading AI Insights...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold gradient-text">Market Intelligence Overview</h1>
          <p className="text-gray-400 mt-1">Real-time analysis from your active workflows</p>
        </div>
        <button className="glass-button px-6 py-2 rounded-xl font-medium text-white shadow-lg flex items-center gap-2">
          <Activity className="w-5 h-5" />
          Live Tracking Active
        </button>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard 
          title="Total Workflows" 
          value={metrics?.total_workflows || 0} 
          icon={<Workflow className="w-6 h-6" />}
          trend={{ value: 12, isPositive: true }}
        />
        <MetricCard 
          title="Reports Generated" 
          value={metrics?.total_reports || 0} 
          icon={<FileText className="w-6 h-6" />}
          trend={{ value: 5, isPositive: true }}
        />
        <MetricCard 
          title="Avg Sentiment" 
          value={`${(metrics?.avg_sentiment_score * 100 || 0).toFixed(1)}%`} 
          icon={<PieChart className="w-6 h-6" />}
          trend={{ value: 2.1, isPositive: false }}
        />
        <MetricCard 
          title="Data Points Scraped" 
          value={metrics?.total_data_points || 0} 
          icon={<Activity className="w-6 h-6" />}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Trend Chart */}
        <div className="glass-card p-6 rounded-2xl lg:col-span-2">
          <h2 className="text-xl font-bold mb-6">Sentiment Trends</h2>
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
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" vertical={false} />
                <XAxis dataKey="date" stroke="#9ca3af" axisLine={false} tickLine={false} />
                <YAxis stroke="#9ca3af" axisLine={false} tickLine={false} />
                <Tooltip 
                  contentStyle={{ backgroundColor: 'rgba(10, 15, 30, 0.9)', borderColor: 'rgba(255,255,255,0.1)', borderRadius: '12px' }}
                  itemStyle={{ color: '#fff' }}
                />
                <Area type="monotone" dataKey="positive" stroke="#10b981" fillOpacity={1} fill="url(#colorPositive)" strokeWidth={2} />
                <Area type="monotone" dataKey="negative" stroke="#ef4444" fillOpacity={1} fill="url(#colorNegative)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Sentiment Distribution */}
        <div className="glass-card p-6 rounded-2xl">
          <h2 className="text-xl font-bold mb-6">Overall Sentiment</h2>
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
                  {sentimentData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip 
                  contentStyle={{ backgroundColor: 'rgba(10, 15, 30, 0.9)', borderColor: 'rgba(255,255,255,0.1)', borderRadius: '12px' }}
                />
              </RechartsPie>
            </ResponsiveContainer>
          </div>
          <div className="flex justify-center gap-4 mt-4">
            {sentimentData.map((entry, index) => (
              <div key={entry.label} className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: COLORS[index % COLORS.length] }}></div>
                <span className="text-sm text-gray-400">{entry.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
