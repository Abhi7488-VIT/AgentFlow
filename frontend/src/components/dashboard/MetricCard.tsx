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
    <div className="clay-card p-6 flex flex-col justify-between hover:translate-y-[-2px] transition-all duration-200">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-clay-ink-muted font-medium">{title}</h3>
        <div className="text-white bg-clay-blue p-2.5 rounded-2xl shadow-[inset_0_2px_3px_rgba(255,255,255,0.3),0_3px_0_0_#2563EB]">
          {icon}
        </div>
      </div>
      <div>
        <p className="text-3xl font-bold text-clay-ink mb-2">{value}</p>
        {trend && (
          <p className={`text-sm font-medium ${trend.isPositive ? 'text-clay-green-dark' : 'text-clay-coral-dark'}`}>
            {trend.isPositive ? '↑' : '↓'} {Math.abs(trend.value)}% from last week
          </p>
        )}
      </div>
    </div>
  );
};
