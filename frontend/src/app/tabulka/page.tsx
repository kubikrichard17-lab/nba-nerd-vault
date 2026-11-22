'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Loader2, RefreshCw, Trophy } from 'lucide-react';
import type { StandingsResponse, StandingsTeam } from '@/types/standings';
import { API } from '@/lib/api';


const pct = (v: number) => (v || 0).toFixed(3).replace(/^0/, '');

const TEAM_COLORS: Record<string, string> = {
  ATL: 'bg-red-500/15 text-red-300 border-red-500/30',
  BOS: 'bg-green-500/15 text-green-300 border-green-500/30',
  BKN: 'bg-slate-400/15 text-slate-200 border-slate-400/30',
  CHA: 'bg-purple-500/15 text-purple-300 border-purple-500/30',
  CHI: 'bg-red-500/15 text-red-300 border-red-500/30',
  CLE: 'bg-amber-700/20 text-amber-300 border-amber-600/30',
  DAL: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  DEN: 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30',
  DET: 'bg-red-500/15 text-red-300 border-red-500/30',
  GSW: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  HOU: 'bg-red-500/15 text-red-300 border-red-500/30',
  IND: 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30',
  LAC: 'bg-red-500/15 text-red-300 border-red-500/30',
  LAL: 'bg-purple-500/15 text-purple-300 border-purple-500/30',
  MEM: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
  MIA: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
  MIL: 'bg-green-500/15 text-green-300 border-green-500/30',
  MIN: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
  NOP: 'bg-amber-700/20 text-amber-300 border-amber-600/30',
  NYK: 'bg-orange-500/15 text-orange-300 border-orange-500/30',
  OKC: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  ORL: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  PHI: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  PHX: 'bg-orange-500/15 text-orange-300 border-orange-500/30',
  POR: 'bg-red-500/15 text-red-300 border-red-500/30',
  SAC: 'bg-purple-500/15 text-purple-300 border-purple-500/30',
  SAS: 'bg-slate-400/15 text-slate-200 border-slate-400/30',
  TOR: 'bg-red-500/15 text-red-300 border-red-500/30',
  UTA: 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30',
  WAS: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
};

const DIVISION_CZ: Record<string, string> = {
  Atlantic: 'Atlantická',
  Central: 'Centrální',
  Southeast: 'Jihovýchodní',
  Northwest: 'Severozápadní',
  Pacific: 'Pacifická',
  Southwest: 'Jihozápadní',
};

const DIVISION_ORDER: Record<string, string[]> = {
  East: ['Atlantic', 'Central', 'Southeast'],
  West: ['Northwest', 'Pacific', 'Southwest'],
};

const streakClass = (s: string) =>
  s?.startsWith('W') ? 'text-emerald-400' : s?.startsWith('L') ? 'text-rose-400' : 'text-slate-400';

const renderRow = (t: StandingsTeam, keySuffix = '') => {
  const playoff = t.seed <= 6;
  const playIn = t.seed === 7 || t.seed === 8;
  return (
    <tr
      key={`${t.team_id}${keySuffix}`}
      className="border-b border-slate-800/60 last:border-0 hover:bg-slate-800/40 transition-colors"
    >
      <td className="py-2 pl-3 pr-1">
        <span
          className={`inline-flex items-center justify-center w-5 h-5 rounded text-[11px] font-bold ${
            playoff
              ? 'bg-emerald-500/20 text-emerald-300'
              : playIn
                ? 'bg-amber-500/20 text-amber-300'
                : 'bg-slate-800 text-slate-500'
          }`}
          title={playoff ? 'Přímé play-off' : playIn ? 'Play-in' : 'Mimo play-off'}
        >
          {t.seed}
        </span>
      </td>
      <td className="py-2 px-1">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={`px-1.5 py-0.5 rounded text-[10px] font-black border shrink-0 ${
              TEAM_COLORS[t.abbr] || 'bg-slate-800 text-slate-300 border-slate-700'
            }`}
          >
            {t.abbr}
          </span>
          <span className="truncate font-semibold text-slate-200">{t.name}</span>
        </div>
      </td>
      <td className="py-2 px-1 text-center font-bold text-slate-100 tabular-nums">{t.wins}</td>
      <td className="py-2 px-1 text-center text-slate-400 tabular-nums">{t.losses}</td>
      <td className="py-2 px-1 text-center font-semibold text-slate-200 tabular-nums">
        {pct(t.win_pct)}
      </td>
      <td className="py-2 px-1 text-center text-slate-400 tabular-nums hidden sm:table-cell">
        {t.seed === 1 ? '–' : (t.games_back || 0).toFixed(1)}
      </td>
      <td className="py-2 px-1 text-center text-slate-400 tabular-nums hidden md:table-cell">
        {t.home}
      </td>
      <td className="py-2 px-1 text-center text-slate-400 tabular-nums hidden md:table-cell">
        {t.road}
      </td>
      <td className="py-2 px-1 text-center text-slate-400 tabular-nums hidden lg:table-cell">
        {t.l10}
      </td>
      <td className={`py-2 px-1 text-center font-semibold tabular-nums ${streakClass(t.streak)}`}>
        {t.streak || '–'}
      </td>
      <td className="py-2 px-1 text-center text-slate-400 tabular-nums hidden xl:table-cell">
        {t.ppg} : {t.opp_ppg}
      </td>
      <td
        className={`py-2 pr-3 pl-1 text-center font-semibold tabular-nums hidden xl:table-cell ${
          t.diff > 0 ? 'text-emerald-400' : t.diff < 0 ? 'text-rose-400' : 'text-slate-400'
        }`}
      >
        {t.diff > 0 ? '+' : ''}
        {t.diff}
      </td>
      <td className="py-2 px-2">
        <div className="flex items-center justify-center gap-1">
          {(t.form || []).length === 0 && <span className="text-slate-600 text-xs">–</span>}
          {(t.form || []).map((g, i) => (
            <span
              key={`${g.game_id}-${i}`}
              title={`${g.date} · ${g.wl === 'W' ? 'výhra' : 'prohra'} ${g.pts}:${g.opp_pts ?? '?'} ${
                g.home ? 'doma' : 'venku'
              } proti ${g.opponent}`}
              className={`w-5 h-5 rounded text-[10px] font-black flex items-center justify-center border ${
                g.wl === 'W'
                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                  : 'bg-rose-500/20 text-rose-300 border-rose-500/40'
              }`}
            >
              {g.wl}
            </span>
          ))}
        </div>
      </td>
    </tr>
  );
};

const ConferenceTable: React.FC<{
  title: string;
  accent: string;
  teams: StandingsTeam[];
  byDivision: boolean;
  conference: 'East' | 'West';
}> = ({ title, accent, teams, byDivision, conference }) => (
  <div className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
    <div className={`px-4 py-3 border-b border-slate-800 flex items-center justify-between ${accent}`}>
      <h2 className="text-sm font-black uppercase tracking-widest">{title}</h2>
      <span className="text-[11px] text-slate-400 font-semibold">{teams.length} týmů</span>
    </div>

    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
            <th className="py-2 pl-3 pr-1 text-left font-bold">#</th>
            <th className="py-2 px-1 text-left font-bold">Tým</th>
            <th className="py-2 px-1 text-center font-bold">V</th>
            <th className="py-2 px-1 text-center font-bold">P</th>
            <th className="py-2 px-1 text-center font-bold">%</th>
            <th className="py-2 px-1 text-center font-bold hidden sm:table-cell">Ztráta</th>
            <th className="py-2 px-1 text-center font-bold hidden md:table-cell">Doma</th>
            <th className="py-2 px-1 text-center font-bold hidden md:table-cell">Venku</th>
            <th className="py-2 px-1 text-center font-bold hidden lg:table-cell">L10</th>
            <th className="py-2 px-1 text-center font-bold">Série</th>
            <th className="py-2 px-1 text-center font-bold hidden xl:table-cell">Skóre</th>
            <th className="py-2 pr-3 pl-1 text-center font-bold hidden xl:table-cell">Rozdíl</th>
            <th className="py-2 px-2 text-center font-bold">Forma</th>
          </tr>
        </thead>
        <tbody>
          {byDivision
            ? DIVISION_ORDER[conference].flatMap((division) => {
                const group = teams
                  .filter((t) => t.division === division)
                  .sort((a, b) => b.win_pct - a.win_pct || b.wins - a.wins);
                if (!group.length) return [];
                return [
                  <tr key={`h-${division}`} className="bg-slate-800/60">
                    <td colSpan={12} className="py-1.5 pl-3 pr-3">
                      <span className="text-[11px] font-black uppercase tracking-widest text-orange-300">
                        {DIVISION_CZ[division] || division} divize
                      </span>
                      <span className="ml-2 text-[10px] text-slate-500">
                        {group.length} týmů
                      </span>
                    </td>
                  </tr>,
                  ...group.map((t) => renderRow(t, '-div')),
                ];
              })
            : teams.map((t) => renderRow(t))}
        </tbody>
      </table>
    </div>
  </div>
);

export default function TabulkaPage() {
  const [data, setData] = useState<StandingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [byDivision, setByDivision] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/standings`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'neznámá chyba';
      setError(
        msg.includes('fetch')
          ? 'Backend neběží – spusť START.bat a zkus to znovu.'
          : `Tabulku se nepodařilo načíst (${msg}).`,
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const updated = useMemo(() => {
    if (!data?.updated) return '';
    try {
      return new Date(data.updated).toLocaleString('cs-CZ', {
        day: 'numeric',
        month: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return '';
    }
  }, [data?.updated]);

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-white flex items-center gap-3">
            <Trophy className="w-8 h-8 text-orange-400" />
            Tabulka {data?.season ? data.season : ''}
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Rekordy týmů v základní části – východní a západní konference vedle sebe.
            {updated && <span className="text-slate-500"> · aktualizováno {updated}</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
        <div className="flex rounded-lg border border-slate-800 bg-slate-900 p-0.5">
          <button
            onClick={() => setByDivision(false)}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${
              !byDivision ? 'bg-orange-500 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            Konference
          </button>
          <button
            onClick={() => setByDivision(true)}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${
              byDivision ? 'bg-orange-500 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            Divize
          </button>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-slate-900 border border-slate-800 text-sm font-semibold text-slate-300 hover:text-white hover:border-slate-700 disabled:opacity-50 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Obnovit
        </button>
        </div>
      </div>

      {loading && !data && (
        <div className="flex flex-col items-center justify-center py-24 text-slate-400 gap-3">
          <Loader2 className="w-7 h-7 animate-spin text-orange-400" />
          <span className="text-sm">Načítám tabulku…</span>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {data && (
        <>
          <div className="grid gap-5 lg:grid-cols-2">
            <ConferenceTable
              title="Východní konference"
              accent="bg-blue-500/10 text-blue-300"
              teams={data.east}
              byDivision={byDivision}
              conference="East"
            />
            <ConferenceTable
              title="Západní konference"
              accent="bg-rose-500/10 text-rose-300"
              teams={data.west}
              byDivision={byDivision}
              conference="West"
            />
          </div>

          <div className="flex flex-wrap items-center gap-4 text-[11px] text-slate-500">
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded bg-emerald-500/20 border border-emerald-500/40" /> přímé
              play-off (1.–6.)
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded bg-amber-500/20 border border-amber-500/40" /> play-in
              (7.–8.)
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded bg-slate-800 border border-slate-700" /> mimo play-off
            </span>
            <span className="text-slate-600">Zdroj: {data.source}</span>
          </div>
        </>
      )}
    </main>
  );
}
