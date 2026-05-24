import type { ReactNode } from 'react';

interface MetricCardProps {
  title: string;
  value: string | number;
  icon: ReactNode;
  trend?: {
    value: number;
    isPositive: boolean;
  };
}

export const MetricCard = ({ title, value, icon, trend }: MetricCardProps) => {
  return (
    <div className="glass-card p-6 rounded-2xl flex flex-col justify-between hover:shadow-lg transition-shadow">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-gray-400 font-medium">{title}</h3>
        <div className="text-electric-blue bg-blue-500/10 p-2 rounded-xl">
          {icon}
        </div>
      </div>
      <div>
        <p className="text-3xl font-bold text-white mb-2">{value}</p>
        {trend && (
          <p className={`text-sm font-medium ${trend.isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
            {trend.isPositive ? '↑' : '↓'} {Math.abs(trend.value)}% from last week
          </p>
        )}
      </div>
    </div>
  );
};
