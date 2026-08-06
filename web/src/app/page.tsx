'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import InfoButton from '@/components/InfoButton';
import LoadingGraph from '@/components/LoadingGraph';

export default function Home() {
  const [query, setQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const router = useRouter();

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    
    setIsSearching(true);
    
    // Perform search immediately without artificial delay
    router.push(`/search?q=${encodeURIComponent(query)}`);
  };

  return (
    <main className="relative flex flex-col items-center justify-center min-h-screen">
      <InfoButton />

      {isSearching ? (
        <LoadingGraph />
      ) : (
        <div className="w-full max-w-2xl px-6 flex flex-col items-center animate-in fade-in zoom-in duration-500">
          <h1 className="text-5xl font-bold mb-10 tracking-widest text-white/90">
            FEEDO
          </h1>
          <form onSubmit={handleSearch} className="w-full relative group">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full bg-[#111111]/80 backdrop-blur-md border border-[#333] rounded-full px-6 py-4 text-lg text-white placeholder-gray-500 outline-none focus:border-white/50 focus:shadow-[0_0_20px_rgba(255,255,255,0.1)] transition-all"
              placeholder="Search decentralized Web3 protocols..."
              autoFocus
            />
            <button 
              type="submit"
              className="absolute right-4 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white transition-colors"
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
              </svg>
            </button>
          </form>

          <div className="mt-12 text-center max-w-lg">
            <p className="text-[#666] text-xs font-mono leading-relaxed">
              Feedo is a semantic search engine. Sites indexed automatically are static snapshots demonstrating P2P speed. For fully interactive dApps, project authors deploy their native builds directly to the network.
            </p>
          </div>
        </div>
      )}
    </main>
  );
}
