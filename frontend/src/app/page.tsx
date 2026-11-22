'use client';

import React, { useState, useEffect } from 'react';
import { PlayerProfile } from '@/types';
import { PlayerSearch } from '@/components/PlayerSearch';
import { PlayerInfobox } from '@/components/PlayerInfobox';
import { StatsTabs } from '@/components/StatsTabs';
import { LastGameCard } from '@/components/LastGameCard';
import { Loader2, AlertCircle, RefreshCw } from 'lucide-react';
import { API } from '@/lib/api';

export default function HomePage() {
  const [selectedPlayerId, setSelectedPlayerId] = useState<number>(893); // Default Michael Jordan
  const [initialized, setInitialized] = useState(false);

  // Podpora odkazu z žebříčků lídrů: /?player=2544
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const raw = params.get('player');
      if (raw && /^\d+$/.test(raw)) {
        setSelectedPlayerId(Number(raw));
      }
    } catch {
      /* ignore */
    }
    setInitialized(true);
  }, []);
  const [player, setPlayer] = useState<PlayerProfile | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPlayer = async (id: number) => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/players/${id}`);
      if (!res.ok) {
        throw new Error('Hráče se nepodařilo načíst ze serveru.');
      }
      const data = await res.json();
      setPlayer(data);
    } catch (err: any) {
      console.error(err);
      setError(err.message || 'Chyba připojení k backendu.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (!initialized) return;
    fetchPlayer(selectedPlayerId);
  }, [selectedPlayerId, initialized]);

  return (
    <div className="space-y-6 sm:space-y-8">
      {/* Top Search Section */}
      <section className="text-center space-y-4 max-w-3xl mx-auto">
        <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-white">
          Vyhledávání & Profil hráče NBA
        </h1>
        <p className="text-sm sm:text-base text-slate-400">
          Procházej detailní kariérní statistiky, fyzické parametry, ocenění a AI scouting report legend i současných hvězd.
        </p>

        <PlayerSearch
          onSelectPlayer={(id) => setSelectedPlayerId(id)}
          selectedPlayerId={selectedPlayerId}
        />
      </section>

      {/* Loading state */}
      {isLoading && (
        <div className="flex flex-col items-center justify-center p-16 space-y-3 bg-slate-900/40 rounded-2xl border border-slate-800">
          <Loader2 className="w-10 h-10 animate-spin text-orange-500" />
          <p className="text-sm font-semibold text-slate-300">
            Načítám kompletní profil hráče (lokální SQLite DB)...
          </p>
        </div>
      )}

      {/* Error state */}
      {error && !isLoading && (
        <div className="p-6 rounded-2xl bg-red-950/40 border border-red-800/80 text-center max-w-xl mx-auto space-y-3">
          <AlertCircle className="w-8 h-8 text-red-400 mx-auto" />
          <h3 className="font-bold text-red-200">Nepodařilo se načíst data hráče</h3>
          <p className="text-xs text-red-300">{error}</p>
          <button
            onClick={() => fetchPlayer(selectedPlayerId)}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-red-600 hover:bg-red-500 text-white text-xs font-bold transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Zkusit znovu
          </button>
        </div>
      )}

      {/* Main Content Layout (Left Infobox + Right StatsTabs) */}
      {!isLoading && player && (
        <div className="flex flex-col lg:flex-row gap-6 items-start">
          {/* Left Wikipedia-style Infobox */}
          <PlayerInfobox player={player} />

          {/* Right: Last Game + Modular Tabs Panel */}
          <div className="flex flex-col gap-4 flex-1 min-w-0">
            <LastGameCard playerId={player.id} isActive={player.is_active} />
            <StatsTabs
              player={player}
              onSelectPlayer={(id) => setSelectedPlayerId(id)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
