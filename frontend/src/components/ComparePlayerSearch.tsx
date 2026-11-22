'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Search, Loader2, UserCheck, X, ChevronDown, Check } from 'lucide-react';
import { SearchResultItem, ComparePlayerSummary } from '@/types';
import { API } from '@/lib/api';

interface ComparePlayerSearchProps {
  label: string;
  color: 'orange' | 'sky';
  selectedPlayer: ComparePlayerSummary | null;
  onSelectPlayer: (playerId: number) => void;
}

export const ComparePlayerSearch: React.FC<ComparePlayerSearchProps> = ({
  label,
  color,
  selectedPlayer,
  onSelectPlayer,
}) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const isOrange = color === 'orange';
  const borderFocus = isOrange ? 'focus:ring-orange-500/50 focus:border-orange-500' : 'focus:ring-sky-500/50 focus:border-sky-500';
  const accentText = isOrange ? 'text-orange-400' : 'text-sky-400';
  const badgeBg = isOrange ? 'bg-orange-500 text-white' : 'bg-sky-500 text-white';

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
    if (!isOpen) return;

    const timeoutId = setTimeout(async () => {
      setIsLoading(true);
      try {
        const url = query.trim()
          ? `${API}/api/players/search?q=${encodeURIComponent(query.trim())}&limit=12`
          : `${API}/api/players/search?limit=10`;
        const res = await fetch(url);
        if (res.ok) {
          const data = await res.json();
          setResults(data);
        }
      } catch (err) {
        console.error('Chyba při vyhledávání v porovnávači:', err);
      } finally {
        setIsLoading(false);
      }
    }, 180);

    return () => clearTimeout(timeoutId);
  }, [query, isOpen]);

  const handleSelect = (playerId: number) => {
    onSelectPlayer(playerId);
    setIsOpen(false);
    setQuery('');
  };

  return (
    <div ref={wrapperRef} className="relative w-full">
      {/* Current Selection / Toggle bar */}
      <div
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-between p-2.5 bg-slate-900 border border-slate-700/80 hover:border-slate-600 rounded-xl cursor-pointer transition-all shadow-sm"
      >
        <div className="flex items-center space-x-3 overflow-hidden">
          <div className="w-10 h-10 rounded-full bg-slate-800 border border-slate-700 overflow-hidden shrink-0 flex items-center justify-center">
            {selectedPlayer ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={selectedPlayer.headshot_url || `https://cdn.nba.com/headshots/nba/latest/1040x760/${selectedPlayer.id}.png`}
                alt={selectedPlayer.full_name}
                onError={(e) => {
                  (e.target as HTMLImageElement).src =
                    'https://cdn.nba.com/headshots/nba/latest/1040x760/fallback.png';
                }}
                className="w-full h-full object-cover object-top"
              />
            ) : (
              <Search className="w-4 h-4 text-slate-500" />
            )}
          </div>
          <div className="truncate">
            <div className="font-bold text-sm text-white truncate">
              {selectedPlayer?.full_name || 'Vyberte hráče...'}
            </div>
            <div className="text-xs text-slate-400 flex items-center gap-1.5">
              <span className={accentText}>
                {selectedPlayer?.position || '-'}
              </span>
              <span>•</span>
              <span>{selectedPlayer?.height_cm ? `${selectedPlayer.height_cm} cm` : '-'}</span>
              <span>•</span>
              <span>{selectedPlayer?.weight_kg ? `${selectedPlayer.weight_kg} kg` : '-'}</span>
            </div>
          </div>
        </div>

        <button
          type="button"
          className="text-xs font-semibold px-2 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 flex items-center gap-1 shrink-0 ml-2"
        >
          <span>Změnit</span>
          <ChevronDown className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Autocomplete Dropdown Search */}
      {isOpen && (
        <div className="absolute z-50 left-0 right-0 mt-2 bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl overflow-hidden">
          {/* Search Input inside Dropdown */}
          <div className="p-2 border-b border-slate-800 flex items-center gap-2 bg-slate-950/80">
            <Search className="w-4 h-4 text-slate-400 ml-2 shrink-0" />
            <input
              type="text"
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Hledej libovolného hráče NBA (celá historie)..."
              className={`w-full bg-transparent py-1.5 px-2 text-xs sm:text-sm text-white placeholder-slate-500 focus:outline-none`}
            />
            {query && (
              <button
                onClick={() => setQuery('')}
                className="text-slate-400 hover:text-white p-1"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Results List */}
          <div className="max-h-64 overflow-y-auto divide-y divide-slate-800/60">
            {isLoading && (
              <div className="p-4 text-center text-xs text-slate-400 flex items-center justify-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin text-orange-400" />
                <span>Vyhledávám v databázi NBA...</span>
              </div>
            )}

            {!isLoading && results.length === 0 && (
              <div className="p-4 text-center text-xs text-slate-500 italic">
                Žádný hráč neodpovídá hledanému výrazu.
              </div>
            )}

            {!isLoading &&
              results.map((player) => {
                const isSelected = selectedPlayer?.id === player.id;
                return (
                  <div
                    key={player.id}
                    onClick={() => handleSelect(player.id)}
                    className={`flex items-center justify-between px-3 py-2.5 hover:bg-slate-800/80 cursor-pointer transition-colors ${
                      isSelected ? 'bg-slate-800/60' : ''
                    }`}
                  >
                    <div className="flex items-center space-x-2.5 truncate">
                      <div className="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 overflow-hidden shrink-0 flex items-center justify-center">
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
                      <div className="truncate">
                        <div className="text-xs font-bold text-white truncate">
                          {player.full_name}
                        </div>
                        <div className="text-[10px] text-slate-400">
                          {player.is_active ? 'Aktivní v NBA' : 'Bývalý hráč NBA'}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      {player.in_db && (
                        <span className="flex items-center space-x-1 text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 px-1.5 py-0.5 rounded-full font-medium">
                          <UserCheck className="w-2.5 h-2.5" />
                          <span>V DB</span>
                        </span>
                      )}
                      {isSelected && (
                        <Check className={`w-4 h-4 ${accentText}`} />
                      )}
                    </div>
                  </div>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
};
