'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Search, Loader2, Sparkles, UserCheck } from 'lucide-react';
import { SearchResultItem } from '@/types';
import { API } from '@/lib/api';

interface PlayerSearchProps {
  onSelectPlayer: (playerId: number) => void;
  selectedPlayerId?: number;
}

const POPULAR_LEGENDS = [
  { id: 893, name: 'Michael Jordan' },
  { id: 2544, name: 'LeBron James' },
  { id: 201939, name: 'Stephen Curry' },
  { id: 203999, name: 'Nikola Jokič' },
  { id: 977, name: 'Kobe Bryant' },
  { id: 406, name: 'Shaquille O\'Neal' },
  { id: 1629029, name: 'Luka Dončić' },
];

export const PlayerSearch: React.FC<PlayerSearchProps> = ({
  onSelectPlayer,
  selectedPlayerId,
}) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    const timeoutId = setTimeout(async () => {
      if (!query.trim()) {
        // Load default seeded players if query is empty
        try {
          const res = await fetch(`${API}/api/players/search?limit=10`);
          if (res.ok) {
            const data = await res.json();
            setResults(data);
          }
        } catch {
          // ignore network error
        }
        return;
      }

      setIsLoading(true);
      try {
        const res = await fetch(`${API}/api/players/search?q=${encodeURIComponent(query)}&limit=12`);
        if (res.ok) {
          const data = await res.json();
          setResults(data);
          setIsOpen(true);
        }
      } catch (err) {
        console.error('Chyba při vyhledávání hráčů:', err);
      } finally {
        setIsLoading(false);
      }
    }, 200);

    return () => clearTimeout(timeoutId);
  }, [query]);

  const handleSelect = (playerId: number) => {
    onSelectPlayer(playerId);
    setIsOpen(false);
    setQuery('');
  };

  return (
    <div ref={wrapperRef} className="relative w-full max-w-3xl mx-auto">
      {/* Search Input Bar */}
      <div className="relative flex items-center">
        <div className="absolute left-4 pointer-events-none text-slate-400">
          {isLoading ? (
            <Loader2 className="w-5 h-5 animate-spin text-orange-400" />
          ) : (
            <Search className="w-5 h-5 text-orange-400" />
          )}
        </div>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setIsOpen(true)}
          placeholder="Vyhledej aktivního hráče nebo legendu NBA (např. Jordan, LeBron, Curry, Bird)..."
          className="w-full pl-12 pr-4 py-3.5 bg-slate-900/90 border border-slate-700/80 rounded-2xl text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-orange-500/50 focus:border-orange-500 text-sm sm:text-base shadow-xl transition-all"
        />
        {query && (
          <button
            onClick={() => setQuery('')}
            className="absolute right-4 text-xs font-semibold text-slate-400 hover:text-white px-2 py-1 rounded bg-slate-800"
          >
            Vymazat
          </button>
        )}
      </div>

      {/* Popular Quick Chips */}
      <div className="flex flex-wrap items-center gap-1.5 sm:gap-2 mt-2.5 px-1">
        <span className="text-xs text-slate-400 flex items-center gap-1 font-medium mr-1">
          <Sparkles className="w-3.5 h-3.5 text-amber-400" /> Rychlý výběr:
        </span>
        {POPULAR_LEGENDS.map((legend) => (
          <button
            key={legend.id}
            onClick={() => handleSelect(legend.id)}
            className={`text-xs px-2.5 py-1 rounded-full border transition-all ${
              selectedPlayerId === legend.id
                ? 'bg-orange-500 text-white border-orange-400 font-bold shadow-md'
                : 'bg-slate-900/80 text-slate-300 border-slate-700/70 hover:border-orange-500/50 hover:text-white hover:bg-slate-800'
            }`}
          >
            {legend.name}
          </button>
        ))}
      </div>

      {/* Autocomplete Dropdown */}
      {isOpen && results.length > 0 && (
        <div className="absolute z-50 w-full mt-2 bg-slate-900 border border-slate-700/80 rounded-2xl shadow-2xl overflow-hidden max-h-96 overflow-y-auto">
          <div className="p-2 border-b border-slate-800 text-[11px] font-bold tracking-wider text-slate-400 uppercase px-3">
            Nalezení hráči ({results.length})
          </div>
          <div className="divide-y divide-slate-800/60">
            {results.map((player) => (
              <div
                key={player.id}
                onClick={() => handleSelect(player.id)}
                className="flex items-center justify-between px-4 py-3 hover:bg-slate-800/80 cursor-pointer transition-colors group"
              >
                <div className="flex items-center space-x-3">
                  <div className="w-10 h-10 rounded-full bg-slate-800 border border-slate-700 overflow-hidden flex items-center justify-center shrink-0">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`https://cdn.nba.com/headshots/nba/latest/1040x760/${player.id}.png`}
                      alt={player.full_name}
                      onError={(e) => {
                        (e.target as HTMLImageElement).src =
                          'https://cdn.nba.com/headshots/nba/latest/1040x760/fallback.png';
                      }}
                      className="w-full h-full object-cover object-top"
                    />
                  </div>
                  <div>
                    <div className="font-semibold text-slate-100 group-hover:text-orange-400 transition-colors">
                      {player.full_name}
                    </div>
                    <div className="text-xs text-slate-400 flex items-center gap-2">
                      <span>ID: {player.id}</span>
                      <span>•</span>
                      <span className={player.is_active ? 'text-emerald-400' : 'text-slate-500'}>
                        {player.is_active ? 'Aktivní hráč NBA' : 'Historická legenda'}
                      </span>
                    </div>
                  </div>
                </div>

                {player.in_db && (
                  <span className="flex items-center space-x-1 text-[11px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded-full font-medium">
                    <UserCheck className="w-3 h-3" />
                    <span>V databázi DB</span>
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
