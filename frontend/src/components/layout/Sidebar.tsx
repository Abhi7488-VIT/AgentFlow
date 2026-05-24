import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Workflow, FileText, Settings, Bot } from 'lucide-react';

export const Sidebar = () => {
  const links = [
    { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
    { to: '/workflows', icon: Workflow, label: 'Workflows' },
    { to: '/reports', icon: FileText, label: 'Reports' },
    { to: '/settings', icon: Settings, label: 'Settings' },
  ];

  return (
    <aside className="w-64 h-screen glass-card border-r border-white/5 flex flex-col fixed left-0 top-0">
      <div className="p-6 flex items-center gap-3 border-b border-white/5">
        <Bot className="text-electric-blue w-8 h-8" />
        <span className="text-xl font-bold gradient-text">AgentFlow</span>
      </div>
      
      <nav className="flex-1 p-4 space-y-2">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 ${
                isActive 
                  ? 'bg-white/10 text-electric-blue shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]' 
                  : 'text-gray-400 hover:text-white hover:bg-white/5'
              }`
            }
          >
            <link.icon className="w-5 h-5" />
            <span className="font-medium">{link.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="p-6 border-t border-white/5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-tr from-electric-blue to-violet flex items-center justify-center text-white font-bold">
            AD
          </div>
          <div>
            <p className="text-sm font-semibold">Admin User</p>
            <p className="text-xs text-gray-400">admin@agentflow.ai</p>
          </div>
        </div>
      </div>
    </aside>
  );
};
