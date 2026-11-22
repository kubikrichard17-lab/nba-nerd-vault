'use client';

import React, { useState, useEffect } from 'react';
import { Loader2, CalendarDays, TrendingUp, TrendingDown, Minus, Swords } from 'lucide-react';
import { API } from '@/lib/api';

interface LastGameData {
  game_date: string;
  season_id: string;
  matchup: string;
  my_team: string;
  opp_team: string;
  is_home: boolean;
  wl: string;
  minutes: string;
  pts: number;
  reb: number;
  ast: number;
  stl: number;
  blk: number;
  tov: number;
  fgm: number;
  fga: number;
  fg_pct: number;
  fg3m: number;
  fg3a: number;
  fg3_pct: number;
  ftm: number;
  fta: number;
  ft_pct: number;
  plus_minus: number;
}

interface LastGameCardProps {
  playerId: number;
  isActive: boolean;
}

// "22024" / "22002" → "2024-25" (NBA vrací sezónu s předponou typu)
const formatSeason = (raw: string): string => {
  const digits = String(raw || '').replace(/\D/g, '');
  if (digits.length < 4) return raw;
  const year = Number(digits.slice(-4));
  if (!year) return raw;
  return `${year}-${String((year + 1) % 100).padStart(2, '0')}`;
};

export const LastGameCard: React.FC<LastGameCardProps> = ({ playerId, isActive }) => {
  const [data, setData] = useState<LastGameData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!playerId) return;
    setIsLoading(true);
    setError(null);
    setData(null);

    fetch(`${API}/api/players/${playerId}/last-game`)
      .then((res) => {
        if (!res.ok) throw new Error('Zápas nenalezen');
        return res.json();
      })
      .then((d) => setData(d))
      .catch(() => setError('Data posledního zápasu nejsou dostupná.'))
      .finally(() => setIsLoading(false));
  }, [playerId]);

  const fmtPct = (v: number) => `${Math.round(v * 100)}%`;
  const fmtDate = (s: string) => {
    // NBA format: "NOV 19, 2024" → "19. 11. 2024"
    try {
      const d = new Date(s);
      if (isNaN(d.getTime())) return s;
      return d.toLocaleDateString('cs-CZ', { day: 'numeric', month: 'numeric', year: 'numeric' });
    } catch {
      return s;
    }
  };

  const isWin = data?.wl === 'W';
  const plusMinusColor =
    (data?.plus_minus ?? 0) > 0
      ? 'text-emerald-400'
      : (data?.plus_minus ?? 0) < 0
      ? 'text-red-400'
      : 'text-slate-400';

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-slate-900/60 border border-slate-800 text-xs text-slate-400">
        <Loader2 className="w-3.5 h-3.5 animate-spin text-orange-400" />
        Načítám poslední zápas...
      </div>
    );
  }

  if (error || !data) {
    // Silently hide for retired players — no need to show error
    if (!isActive) return null;
    return (
      <div className="px-4 py-3 rounded-xl bg-slate-900/60 border border-slate-800 text-xs text-slate-500 italic">
        Data posledního zápasu nejsou k dispozici.
      </div>
    );
  }

  return (
    <div className={`rounded-2xl border p-4 sm:p-5 ${isWin ? 'bg-emerald-950/30 border-emerald-700/40' : 'bg-red-950/20 border-red-700/30'}`}>
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <div className="flex items-center gap-2">
          <Swords className="w-4 h-4 text-orange-400 shrink-0" />
          <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
            Poslední zápas
          </span>
        </div>
        <div className="flex items-center gap-3">
          {/* Win/Loss badge */}
          <span
            className={`text-xs font-black px-2.5 py-1 rounded-lg ${
              isWin ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40' : 'bg-red-500/20 text-red-300 border border-red-500/40'
            }`}
          >
            {isWin ? 'Výhra' : 'Prohra'}
          </span>
          {/* Date */}
          <span className="flex items-center gap-1 text-[11px] text-slate-400">
            <CalendarDays className="w-3 h-3" />
            {fmtDate(data.game_date)}
          </span>
        </div>
      </div>

      {/* Matchup + main stats */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center">
        {/* Matchup info */}
        <div className="shrink-0 text-center sm:text-left">
          <div className="text-lg font-black text-white tracking-tight">{data.matchup}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">
            {data.is_home ? 'Domácí zápas' : 'Venkovní zápas'} • {data.minutes} min
          </div>
        </div>

        {/* Divider */}
        <div className="hidden sm:block w-px h-10 bg-slate-700/60" />

        {/* Key stats row */}
        <div className="flex flex-wrap gap-3 flex-1">
          {/* PTS — biggest */}
          <div className="flex flex-col items-center bg-slate-900/60 rounded-xl px-4 py-2 border border-slate-800/60 min-w-[56px]">
            <span className="text-2xl font-black text-white leading-none">{data.pts}</span>
            <span className="text-[10px] text-orange-400 font-bold uppercase tracking-wider mt-0.5">Body</span>
          </div>

          {[
            { label: 'Reb', value: data.reb },
            { label: 'Ast', value: data.ast },
            { label: 'Stl', value: data.stl },
            { label: 'Blk', value: data.blk },
            { label: 'Tov', value: data.tov, negative: true },
          ].map(({ label, value, negative }) => (
            <div key={label} className="flex flex-col items-center bg-slate-900/60 rounded-xl px-3 py-2 border border-slate-800/60 min-w-[48px]">
              <span className={`text-base font-black leading-none ${negative && value > 2 ? 'text-red-400' : 'text-white'}`}>
                {value}
              </span>
              <span className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider mt-0.5">{label}</span>
            </div>
          ))}

          {/* +/- */}
          <div className="flex flex-col items-center bg-slate-900/60 rounded-xl px-3 py-2 border border-slate-800/60 min-w-[48px]">
            <span className={`text-base font-black leading-none ${plusMinusColor}`}>
              {data.plus_minus > 0 ? `+${data.plus_minus}` : data.plus_minus}
            </span>
            <span className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider mt-0.5">+/-</span>
          </div>
        </div>
      </div>

      {/* Shooting line */}
      <div className="mt-3 pt-3 border-t border-slate-800/60 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-300">
        <span>
          <span className="text-slate-500">FG: </span>
          <span className="font-semibold">{data.fgm}/{data.fga}</span>
          <span className="text-slate-400"> ({fmtPct(data.fg_pct)})</span>
        </span>
        <span>
          <span className="text-slate-500">3B: </span>
          <span className="font-semibold">{data.fg3m}/{data.fg3a}</span>
          <span className="text-slate-400"> ({fmtPct(data.fg3_pct)})</span>
        </span>
        <span>
          <span className="text-slate-500">TH: </span>
          <span className="font-semibold">{data.ftm}/{data.fta}</span>
          <span className="text-slate-400"> ({fmtPct(data.ft_pct)})</span>
        </span>
        <span className="ml-auto text-[11px] text-slate-500">
          Sezóna {formatSeason(data.season_id)}
        </span>
      </div>
    </div>
  );
};
