import { useState } from 'react';
import { Link, Outlet } from 'react-router-dom';
import { Sparkles } from 'lucide-react';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { useAuth } from '../../context/AuthContext';

export const Layout = () => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const { isDemo } = useAuth();

  return (
    <div className="min-h-screen bg-clay-bg text-clay-ink flex">
      <Sidebar isOpen={isSidebarOpen} setIsOpen={setIsSidebarOpen} />
      <div className="flex-1 md:ml-64 flex flex-col w-full min-w-0">
        <Header toggleSidebar={() => setIsSidebarOpen(true)} />
        {isDemo && (
          <div className="mx-4 md:mx-8 mt-4 px-4 py-3 rounded-2xl bg-clay-purple/10 border-2 border-clay-purple/20 text-sm text-clay-purple-dark flex flex-wrap items-center gap-2">
            <Sparkles className="w-4 h-4 shrink-0" />
            <span>You're exploring the shared demo workspace. Anything you run here is visible to other visitors.</span>
            <Link to="/signup" className="font-semibold underline underline-offset-2 hover:text-clay-ink">
              Create your own workspace
            </Link>
          </div>
        )}
        <main className="flex-1 p-4 md:p-8 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
};
