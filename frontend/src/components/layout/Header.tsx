import { Bell, Search } from 'lucide-react';

export const Header = () => {
  return (
    <header className="h-20 glass-card border-b border-white/5 flex items-center justify-between px-8 sticky top-0 z-10 backdrop-blur-md">
      <div className="flex items-center gap-4 bg-white/5 px-4 py-2 rounded-xl border border-white/5 w-96">
        <Search className="w-5 h-5 text-gray-400" />
        <input 
          type="text" 
          placeholder="Search workflows, reports..." 
          className="bg-transparent border-none outline-none text-sm w-full text-white placeholder-gray-500"
        />
      </div>

      <div className="flex items-center gap-6">
        <button className="relative text-gray-400 hover:text-white transition-colors">
          <Bell className="w-6 h-6" />
          <span className="absolute top-0 right-0 w-2.5 h-2.5 bg-red-500 rounded-full border-2 border-[#0a0f1e]"></span>
        </button>
      </div>
    </header>
  );
};
