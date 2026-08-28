import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Workflow, FileText, Settings, Bot, LogOut, X, Users } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

interface SidebarProps {
  isOpen: boolean;
  setIsOpen: (isOpen: boolean) => void;
}

export const Sidebar = ({ isOpen, setIsOpen }: SidebarProps) => {
  const { user, logout } = useAuth();
  const links = [
    { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
    { to: '/workflows', icon: Workflow, label: 'Workflows' },
    { to: '/reports', icon: FileText, label: 'Reports' },
    { to: '/users', icon: Users, label: 'Users' },
    { to: '/settings', icon: Settings, label: 'Settings' },
  ];

  return (
    <>
      {/* Mobile backdrop overlay */}
      {isOpen && (
        <div 
          className="fixed inset-0 bg-black/30 backdrop-blur-sm z-40 md:hidden"
          onClick={() => setIsOpen(false)}
        ></div>
      )}

      {/* Sidebar drawer */}
      <aside className={`w-64 h-screen bg-white border-r-2 border-clay-border shadow-[6px_0_20px_rgba(0,0,0,0.06)] flex flex-col fixed left-0 top-0 z-50 transform transition-transform duration-300 ease-in-out ${isOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0`}>
        <div className="p-6 flex items-center justify-between border-b-2 border-clay-border">
          <div className="flex items-center gap-3">
            <Bot className="text-clay-blue w-8 h-8" />
            <span className="text-xl font-bold gradient-text">AgentFlow</span>
          </div>
          <button onClick={() => setIsOpen(false)} className="md:hidden text-clay-ink-muted hover:text-clay-ink">
            <X className="w-6 h-6" />
          </button>
        </div>
        
        <nav className="flex-1 p-4 space-y-2 overflow-y-auto">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              onClick={() => setIsOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 ${
                  isActive
                    ? 'bg-clay-blue/10 text-clay-blue-dark font-semibold shadow-[inset_0_2px_4px_rgba(96,165,250,0.1)]'
                    : 'text-clay-ink-light hover:text-clay-ink hover:bg-clay-blue/5'
                }`
              }
            >
              <link.icon className="w-5 h-5" />
              <span className="font-medium">{link.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="p-6 border-t-2 border-clay-border space-y-4 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-clay-blue shadow-[inset_0_2px_3px_rgba(255,255,255,0.3),0_3px_0_0_#2563EB] flex items-center justify-center text-white font-bold shrink-0">
              {user?.full_name?.substring(0, 2).toUpperCase() || 'U'}
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold truncate text-clay-ink">{user?.full_name || 'User'}</p>
              <p className="text-xs text-clay-ink-muted truncate">{user?.email || ''}</p>
            </div>
          </div>
          <button
            onClick={logout}
            className="w-full flex items-center justify-center gap-2 py-2 px-4 rounded-xl text-sm font-medium text-clay-coral hover:bg-clay-coral/10 hover:text-clay-coral-dark transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Logout
          </button>
        </div>
      </aside>
    </>
  );
};
