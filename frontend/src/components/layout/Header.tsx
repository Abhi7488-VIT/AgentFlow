import { Bell, Search, Menu } from 'lucide-react';

interface HeaderProps {
  toggleSidebar: () => void;
}

export const Header = ({ toggleSidebar }: HeaderProps) => {
  return (
    <header className="h-20 glass-card border-b border-white/5 flex items-center justify-between px-4 md:px-8 sticky top-0 z-10 backdrop-blur-md">
      <div className="flex items-center gap-4">
        <button 
          onClick={toggleSidebar}
          className="md:hidden text-gray-400 hover:text-white p-2"
        >
          <Menu className="w-6 h-6" />
        </button>
        <div className="hidden md:flex items-center gap-4 bg-white/5 px-4 py-2 rounded-xl border border-white/5 w-96">
          <Search className="w-5 h-5 text-gray-400" />
          <input 
            type="text" 
            placeholder="Search workflows, reports..." 
            className="bg-transparent border-none outline-none text-sm w-full text-white placeholder-gray-500"
          />
        </div>
      </div>

      <div className="flex items-center gap-4 md:gap-6">
        <button className="md:hidden text-gray-400 hover:text-white transition-colors">
          <Search className="w-6 h-6" />
        </button>
        <button className="relative text-gray-400 hover:text-white transition-colors">
          <Bell className="w-6 h-6" />
          <span className="absolute top-0 right-0 w-2.5 h-2.5 bg-red-500 rounded-full border-2 border-[#0a0f1e]"></span>
        </button>
      </div>
    </header>
  );
};
