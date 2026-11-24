'use client';

import React, { useEffect, useState } from 'react';
import { ClosestPlayer, ClosestResponse, PlayerProfile } from '@/types';
import type { Fact } from '@/types/facts';

import {
  BarChart3,
  Sparkles,
  BookOpen,
  Target,
  Shield,
  Zap,
  TrendingUp,
  Percent,
  CheckCircle2,
  Activity,
  Users,
  Loader2,
  Building2
} from 'lucide-react';
import { API } from '@/lib/api';

interface StatsTabsProps {
  player: PlayerProfile;
  onSelectPlayer?: (id: number) => void;
}

export const StatsTabs: React.FC<StatsTabsProps> = ({ player, onSelectPlayer }) => {
  const [activeTab, setActiveTab] = useState<'stats' | 'profile'>('stats');
  const [statMode, setStatMode] = useState<'per_game' | 'per_100'>('per_game');
  const [closest, setClosest] = useState<ClosestPlayer | null>(null);
  const [closestData, setClosestData] = useState<ClosestResponse | null>(null);
  const [closestLoading, setClosestLoading] = useState(false);
  const [closestError, setClosestError] = useState<string | null>(null);
  // Která verze hráče se zobrazuje: 'prime' (vrchol), 'early', nebo 'late'
  const [viewKey, setViewKey] = useState<string>('prime');

  // Zobrazená verze: vrchol kariéry, nebo jedna z fází, které hráč prošel
  const activeClosestData: ClosestResponse | null = React.useMemo(() => {
    if (!closestData) return null;
    if (viewKey === 'prime') return closestData;
    const phase = (closestData.career_phases || []).find(
      (item) => item.phase.key === viewKey,
    );
    return phase || closestData;
  }, [closestData, viewKey]);

  // Hráč, který se zobrazuje v hlavní kartě – podle zvolené fáze
  const activeClosest: ClosestPlayer | null =
    (activeClosestData?.closest as ClosestPlayer | null | undefined) ?? closest;

  // Při změně hráče se vždy začíná na vrcholu kariéry
  React.useEffect(() => {
    setViewKey('prime');
  }, [player.id]);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [factsLoading, setFactsLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const loadFacts = async () => {
      setFactsLoading(true);
      try {
        // jen zajímavosti k tomuto hráči – žádné náhradní od jiných
        const res = await fetch(`${API}/api/facts?player_id=${player.id}&shuffle=false`);
        const data = res.ok ? await res.json() : { facts: [] };
        if (!cancelled) setFacts((data.facts || []).slice(0, 4));
      } catch {
        if (!cancelled) setFacts([]);
      } finally {
        if (!cancelled) setFactsLoading(false);
      }
    };
    loadFacts();
    return () => {
      cancelled = true;
    };
  }, [player.id]);

  useEffect(() => {
    let cancelled = false;
    const cacheKey = `player_comp_${player.id}`;
    const loadClosest = async () => {
      setClosestError(null);

      // 1) localStorage – okamžité zobrazení stejného výsledku jako minule
      let cached: ClosestResponse | null = null;
      try {
        const raw = window.localStorage.getItem(cacheKey);
        if (raw) {
          cached = JSON.parse(raw) as ClosestResponse;
          if (cached && cached.closest) {
            setClosest(cached.closest);
            setClosestData(cached);
          }
        }
      } catch {
        cached = null;
      }

      setClosestLoading(!cached);
      try {
        // backend má vlastní cache, takže tohle je jen první výpočet
        const res = await fetch(`${API}/api/players/${player.id}/closest`);
        if (!res.ok) {
          throw new Error('Nejbližšího hráče se nepodařilo spočítat.');
        }
        const data: ClosestResponse = await res.json();
        if (!cancelled) {
          setClosest(data.closest ?? null);
          setClosestData(data);
          try {
            window.localStorage.setItem(cacheKey, JSON.stringify(data));
          } catch {
            /* plná paměť prohlížeče – nevadí, backend má vlastní cache */
          }
        }
      } catch (err: any) {
        if (!cancelled) {
          setClosestError(err.message || 'Nejbližšího hráče se nepodařilo spočítat.');
        }
      } finally {
        if (!cancelled) {
          setClosestLoading(false);
        }
      }
    };
    loadClosest();
    return () => {
      cancelled = true;
    };
  }, [player.id]);

  const summary = player.career_summary;
  const is100 = statMode === 'per_100';
  const clubs = player.clubs || [];

  return (
    <div className="flex-1 bg-slate-900/90 border border-slate-800 rounded-2xl overflow-hidden shadow-xl flex flex-col">
      {/* Top Navigation Switcher Bar */}
      <div className="flex border-b border-slate-800 bg-slate-950/70 p-2 gap-2">
        <button
          onClick={() => setActiveTab('stats')}
          className={`flex-1 flex items-center justify-center space-x-2 py-3 px-4 rounded-xl text-sm font-bold transition-all ${
            activeTab === 'stats'
              ? 'bg-gradient-to-r from-orange-600 to-amber-600 text-white shadow-lg shadow-orange-500/20'
              : 'text-slate-400 hover:text-white hover:bg-slate-900'
          }`}
        >
          <BarChart3 className="w-4 h-4" />
          <span>Statistiky & Sezóny</span>
        </button>

        <button
          onClick={() => setActiveTab('profile')}
          className={`flex-1 flex items-center justify-center space-x-2 py-3 px-4 rounded-xl text-sm font-bold transition-all ${
            activeTab === 'profile'
              ? 'bg-gradient-to-r from-orange-600 to-amber-600 text-white shadow-lg shadow-orange-500/20'
              : 'text-slate-400 hover:text-white hover:bg-slate-900'
          }`}
        >
          <Sparkles className="w-4 h-4 text-amber-300" />
          <span>Herní styl & Profil (AI Scout)</span>
        </button>
      </div>

      {/* Content Area */}
      <div className="p-4 sm:p-6 flex-1">
        {/* ================= TAB 1: STATISTIKY ================= */}
        {activeTab === 'stats' && (
          <div className="space-y-6">
            {/* Header + Mode Switcher */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-800">
              <div>
                <h3 className="text-lg font-bold text-white flex items-center gap-2">
                  <Activity className="w-5 h-5 text-orange-400" />
                  Kariérní a sezónní statistiky
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Celkem odehráno {summary?.gp || player.season_stats.length} utkání v NBA
                </p>
              </div>

              {/* Toggle: Per Game vs Per 100 Possessions */}
              <div className="flex items-center bg-slate-950 p-1 rounded-xl border border-slate-800">
                <button
                  onClick={() => setStatMode('per_game')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                    !is100
                      ? 'bg-orange-500 text-white shadow-md'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  Základní (Na zápas)
                </button>
                <button
                  onClick={() => setStatMode('per_100')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                    is100
                      ? 'bg-orange-500 text-white shadow-md'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  Na 100 držení míče (Per 100)
                </button>
              </div>
            </div>

            {/* Quick Stat Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
              <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800/80">
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                  {is100 ? 'Body / 100' : 'Body (PPG)'}
                </span>
                <div className="text-2xl font-black text-orange-400 mt-1">
                  {is100 ? summary?.poss100_pts : summary?.pts}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">Kariérní průměr</div>
              </div>

              <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800/80">
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                  {is100 ? 'Doskoky / 100' : 'Doskoky (RPG)'}
                </span>
                <div className="text-2xl font-black text-sky-400 mt-1">
                  {is100 ? summary?.poss100_reb : summary?.reb}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">Kariérní průměr</div>
              </div>

              <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800/80">
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                  {is100 ? 'Asistence / 100' : 'Asistence (APG)'}
                </span>
                <div className="text-2xl font-black text-emerald-400 mt-1">
                  {is100 ? summary?.poss100_ast : summary?.ast}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">Kariérní průměr</div>
              </div>

              <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800/80">
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                  {is100 ? 'Zisky / 100' : 'Zisky (SPG)'}
                </span>
                <div className="text-2xl font-black text-amber-400 mt-1">
                  {is100 ? summary?.poss100_stl : summary?.stl}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">Kariérní průměr</div>
              </div>

              <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800/80">
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                  {is100 ? 'Bloky / 100' : 'Bloky (BPG)'}
                </span>
                <div className="text-2xl font-black text-purple-400 mt-1">
                  {is100 ? summary?.poss100_blk : summary?.blk}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">Kariérní průměr</div>
              </div>

              <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800/80">
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                  Střelba FG / 3P %
                </span>
                <div className="text-lg font-bold text-white mt-1">
                  {summary ? `${(summary.fg_pct * 100).toFixed(1)}%` : '-'}
                  <span className="text-xs text-orange-400 ml-1">
                    / {summary ? `${(summary.fg3_pct * 100).toFixed(1)}%` : '-'}
                  </span>
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  Šestky: {summary ? `${(summary.ft_pct * 100).toFixed(1)}%` : '-'}
                </div>
              </div>
            </div>

            {/* Club career: klub + roky */}
            {clubs.length > 0 && (
              <div className="rounded-xl border border-slate-800 bg-slate-950/60 overflow-hidden">
                <div className="p-3 bg-slate-950 border-b border-slate-800 text-xs font-bold text-slate-300 flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <Building2 className="w-4 h-4 text-orange-400" />
                    Kariéra po klubech ({clubs.length})
                  </span>
                  <span className="text-[11px] text-slate-400 font-normal">
                    {clubs[0]?.from_season} – {clubs[clubs.length - 1]?.to_season}
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left border-collapse">
                    <thead>
                      <tr className="bg-slate-900/90 text-slate-400 border-b border-slate-800 font-semibold uppercase tracking-wider text-[11px]">
                        <th className="py-2.5 px-3">Klub</th>
                        <th className="py-2.5 px-2">Roky</th>
                        <th className="py-2.5 px-2 text-right">Z</th>
                        <th className="py-2.5 px-2 text-right text-orange-400 font-bold">PTS</th>
                        <th className="py-2.5 px-2 text-right text-sky-400">REB</th>
                        <th className="py-2.5 px-2 text-right text-emerald-400">AST</th>
                        <th className="py-2.5 px-2 text-right">STL</th>
                        <th className="py-2.5 px-2 text-right">BLK</th>
                        <th className="py-2.5 px-3 text-right">3PM</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 text-slate-200">
                      {clubs.map((club, i) => (
                        <tr key={`${club.team_abbreviation}-${club.from_season}-${i}`} className="hover:bg-slate-900/60 transition-colors">
                          <td className="py-2 px-3 whitespace-nowrap">
                            <span className="font-semibold text-white">{club.team_name}</span>
                            <span className="ml-1.5 text-[10px] font-mono text-slate-500">
                              {club.team_abbreviation}
                            </span>
                          </td>
                          <td className="py-2 px-2 text-slate-400 whitespace-nowrap">
                            {club.from_season === club.to_season
                              ? club.from_season
                              : `${club.from_season} – ${club.to_season}`}
                          </td>
                          <td className="py-2 px-2 text-right">{club.gp}</td>
                          <td className="py-2 px-2 text-right font-bold text-orange-400">{club.pts}</td>
                          <td className="py-2 px-2 text-right text-sky-400">{club.reb}</td>
                          <td className="py-2 px-2 text-right text-emerald-400">{club.ast}</td>
                          <td className="py-2 px-2 text-right">{club.stl}</td>
                          <td className="py-2 px-2 text-right">{club.blk}</td>
                          <td className="py-2 px-3 text-right">{club.fg3m}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Complete Seasons Table */}
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 overflow-hidden">
              <div className="p-3 bg-slate-950 border-b border-slate-800 text-xs font-bold text-slate-300 flex items-center justify-between">
                <span>Všechny odehrané sezóny v NBA ({player.season_stats.length})</span>
                <span className="text-[11px] text-orange-400 font-normal">
                  Režim: {is100 ? 'Na 100 držení míče (Pace-Adjusted)' : 'Průměry na zápas'}
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left border-collapse">
                  <thead>
                    <tr className="bg-slate-900/90 text-slate-400 border-b border-slate-800 font-semibold uppercase tracking-wider text-[11px]">
                      <th className="py-2.5 px-3">Sezóna</th>
                      <th className="py-2.5 px-2">Tým</th>
                      <th className="py-2.5 px-2 text-right">Z</th>
                      <th className="py-2.5 px-2 text-right">MIN</th>
                      <th className="py-2.5 px-2 text-right text-orange-400 font-bold">PTS</th>
                      <th className="py-2.5 px-2 text-right text-sky-400">REB</th>
                      <th className="py-2.5 px-2 text-right text-emerald-400">AST</th>
                      <th className="py-2.5 px-2 text-right">STL</th>
                      <th className="py-2.5 px-2 text-right">BLK</th>
                      <th className="py-2.5 px-2 text-right">TOV</th>
                      <th className="py-2.5 px-2 text-right">FG%</th>
                      <th className="py-2.5 px-2 text-right">3P%</th>
                      <th className="py-2.5 px-3 text-right">FT%</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 text-slate-200">
                    {player.season_stats.map((stat, i) => (
                      <tr key={i} className="hover:bg-slate-900/60 transition-colors">
                        <td className="py-2 px-3 font-semibold text-white whitespace-nowrap">
                          {stat.season_id}
                        </td>
                        <td className="py-2 px-2 text-slate-400 font-mono">
                          {stat.team_abbreviation || '-'}
                        </td>
                        <td className="py-2 px-2 text-right">{stat.gp}</td>
                        <td className="py-2 px-2 text-right text-slate-400">{stat.min_per_game}</td>
                        <td className="py-2 px-2 text-right font-bold text-orange-400">
                          {is100 ? stat.poss100_pts : stat.pts}
                        </td>
                        <td className="py-2 px-2 text-right text-sky-400">
                          {is100 ? stat.poss100_reb : stat.reb}
                        </td>
                        <td className="py-2 px-2 text-right text-emerald-400">
                          {is100 ? stat.poss100_ast : stat.ast}
                        </td>
                        <td className="py-2 px-2 text-right">
                          {is100 ? stat.poss100_stl : stat.stl}
                        </td>
                        <td className="py-2 px-2 text-right">
                          {is100 ? stat.poss100_blk : stat.blk}
                        </td>
                        <td className="py-2 px-2 text-right text-slate-400">
                          {is100 ? stat.poss100_tov : stat.tov}
                        </td>
                        <td className="py-2 px-2 text-right font-mono">
                          {(stat.fg_pct * 100).toFixed(1)}%
                        </td>
                        <td className="py-2 px-2 text-right font-mono">
                          {(stat.fg3_pct * 100).toFixed(1)}%
                        </td>
                        <td className="py-2 px-3 text-right font-mono">
                          {(stat.ft_pct * 100).toFixed(1)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  {/* Summary Footer */}
                  {summary && (
                    <tfoot>
                      <tr className="bg-slate-900 font-bold border-t-2 border-slate-700 text-white">
                        <td className="py-2.5 px-3">Kariéra (Průměr)</td>
                        <td className="py-2.5 px-2 text-slate-400 font-mono">ALL</td>
                        <td className="py-2.5 px-2 text-right">{summary.gp}</td>
                        <td className="py-2.5 px-2 text-right text-slate-400">-</td>
                        <td className="py-2.5 px-2 text-right text-orange-400">
                          {is100 ? summary.poss100_pts : summary.pts}
                        </td>
                        <td className="py-2.5 px-2 text-right text-sky-400">
                          {is100 ? summary.poss100_reb : summary.reb}
                        </td>
                        <td className="py-2.5 px-2 text-right text-emerald-400">
                          {is100 ? summary.poss100_ast : summary.ast}
                        </td>
                        <td className="py-2.5 px-2 text-right">
                          {is100 ? summary.poss100_stl : summary.stl}
                        </td>
                        <td className="py-2.5 px-2 text-right">
                          {is100 ? summary.poss100_blk : summary.blk}
                        </td>
                        <td className="py-2.5 px-2 text-right text-slate-400">{summary.tov}</td>
                        <td className="py-2.5 px-2 text-right font-mono">
                          {(summary.fg_pct * 100).toFixed(1)}%
                        </td>
                        <td className="py-2.5 px-2 text-right font-mono">
                          {(summary.fg3_pct * 100).toFixed(1)}%
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono">
                          {(summary.ft_pct * 100).toFixed(1)}%
                        </td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            </div>
          </div>
        )}

        {/* ================= TAB 2: HERNÍ STYL & PROFIL ================= */}
        {activeTab === 'profile' && (
          <div className="space-y-6">
            {/* AI Scouting Report (Gemini API / AI Scout) */}
            <div className="relative p-5 rounded-2xl bg-gradient-to-br from-slate-950 via-slate-900 to-amber-950/20 border border-amber-500/30 shadow-lg">
              <div className="flex items-center space-x-2 text-amber-400 mb-2.5">
                <Sparkles className="w-5 h-5" />
                <span className="text-xs font-bold uppercase tracking-wider">
                  AI Scouting Report (Gemini API & Lokální DB)
                </span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 font-semibold border border-amber-500/40">
                  Přesně 3 věty
                </span>
              </div>
              <p className="text-sm sm:text-base text-slate-200 leading-relaxed font-serif italic">
                &ldquo;{player.scouting_report || 'Scouting report hráče se generuje.'}&rdquo;
              </p>

              <div className="mt-4 pt-4 border-t border-amber-500/20">
                <div className="flex items-center gap-2 text-amber-300 mb-2">
                  <Users className="w-4 h-4" />
                  <span className="text-xs font-bold uppercase tracking-wider">Nejbližší hráč</span>
                </div>

                {closestLoading && (
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Počítám nejbližšího hráče podle herního stylu, fyzických parametrů a statistik...
                  </div>
                )}

                {/* Přepínač fáze kariéry – jen u hráčů, kteří se výrazně proměnili */}
                {!closestLoading && closestData?.has_major_evolution && (
                  <div className="mb-2">
                    <div className="flex flex-wrap gap-1">
                      {[
                        {
                          key: 'prime',
                          label: 'Vrchol kariéry',
                          hint: closestData.prime?.seasons?.length
                            ? closestData.prime.seasons.join(', ')
                            : undefined,
                        },
                        ...(closestData.career_phases || []).map((phase) => ({
                          key: phase.phase.key,
                          label: phase.phase.label,
                          hint: phase.phase.range,
                        })),
                      ].map((option) => {
                        const active = (viewKey || 'prime') === option.key;
                        return (
                          <button
                            key={option.key}
                            type="button"
                            onClick={() => setViewKey(option.key)}
                            title={option.hint}
                            className={`text-[10px] px-2 py-1 rounded-lg border transition-colors ${
                              active
                                ? 'bg-amber-500/20 border-amber-500/50 text-amber-200 font-semibold'
                                : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-amber-500/40 hover:text-amber-200'
                            }`}
                          >
                            {option.label}
                          </button>
                        );
                      })}
                    </div>
                    {closestData.evolution_note && (
                      <p className="text-[10px] text-slate-500 mt-1.5">
                        {closestData.evolution_note}
                      </p>
                    )}
                  </div>
                )}

                {closestError && !closestLoading && (
                  <p className="text-xs text-red-300">{closestError}</p>
                )}

                {!closestLoading && !closestError && !closest && (
                  <p className="text-xs text-slate-400">
                    V databázi zatím není další hráč, se kterým by šla shoda spočítat.
                  </p>
                )}

                {activeClosest && !closestLoading && (
                  <div className="space-y-3">
                    {/* Hlavní karta shody */}
                    <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                      <div className="flex items-center gap-3 min-w-0 flex-1">
                        {activeClosest.headshot_url ? (
                          <img
                            src={activeClosest.headshot_url}
                            alt={activeClosest.full_name}
                            className="w-12 h-12 rounded-full object-cover border border-amber-500/40 bg-slate-950"
                          />
                        ) : (
                          <div className="w-12 h-12 rounded-full bg-slate-950 border border-amber-500/40" />
                        )}
                        <div className="min-w-0">
                          <p className="text-sm font-bold text-white truncate">
                            {activeClosest.full_name}
                          </p>
                          <p className="text-[11px] text-slate-400">
                            {activeClosest.role_label || activeClosest.position || 'Pozice neuvedena'} ·{' '}
                            <span className="font-bold text-amber-300">
                              {activeClosestData?.match_percentage ?? activeClosest.match_pct} % shoda
                            </span>
                          </p>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-1.5 sm:justify-end">
                        <span className="text-[10px] px-2 py-1 rounded-lg bg-slate-950 border border-slate-700 text-slate-300">
                          Styl {activeClosest.style_pct ?? activeClosest.stylistic_pct} %
                        </span>
                        <span className="text-[10px] px-2 py-1 rounded-lg bg-slate-950 border border-slate-700 text-slate-300">
                          Fyzično {activeClosest.physical_pct} %
                        </span>
                        <span className="text-[10px] px-2 py-1 rounded-lg bg-slate-950 border border-slate-700 text-slate-300">
                          Statistiky {activeClosest.stats_pct ?? activeClosest.statistical_pct} %
                        </span>
                      </div>
                    </div>

                    {/* Jak se shoda určuje */}
                    <p className="text-[10px] text-slate-500">
                      Stejný archetyp a role · podobná kategorie dopadu (superstar se
                      superstarou) · srovnání stylu, fyzična a statistik
                    </p>

                    {/* Zdůvodnění po třech kategoriích */}
                    {activeClosestData?.breakdown && (
                      <div className="grid gap-2 sm:grid-cols-3">
                        {[
                          {
                            key: 'style',
                            label: 'Styl hry',
                            icon: '🎯',
                            text: activeClosestData.style_comparison,
                          },
                          {
                            key: 'physical',
                            label: 'Fyzičnost',
                            icon: '💪',
                            text: activeClosestData.physical_comparison,
                          },
                          {
                            key: 'stats',
                            label: 'Statistiky',
                            icon: '📊',
                            text: activeClosestData.stats_comparison,
                          },
                        ].map((cat) => {
                          const text =
                            cat.text ||
                            (cat.key === 'style'
                              ? activeClosestData.breakdown?.herni_styl
                              : cat.key === 'physical'
                                ? activeClosestData.breakdown?.fyzicko
                                : activeClosestData.breakdown?.statisticky_dopad);
                          if (!text) {
                            return (
                              <div
                                key={cat.key}
                                className="p-2.5 rounded-xl bg-slate-950/70 border border-slate-800"
                              >
                                <p className="text-[10px] font-bold uppercase tracking-wider text-amber-300/90 mb-1">
                                  {cat.icon} {cat.label}
                                </p>
                                <p className="text-[11px] text-slate-500 italic">
                                  Porovnání se právě dopočítává…
                                </p>
                              </div>
                            );
                          }
                          return (
                            <div
                              key={cat.key}
                              className="p-2.5 rounded-xl bg-slate-950/70 border border-slate-800"
                            >
                              <p className="text-[10px] font-bold uppercase tracking-wider text-amber-300/90 mb-1">
                                {cat.icon} {cat.label}
                              </p>
                              <p className="text-[11px] text-slate-300 leading-relaxed">{text}</p>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Kandidáti v pořadí, jak je vypsala AI, s důvodem */}
                    {activeClosestData?.top_3_candidates &&
                      activeClosestData.top_3_candidates.length > 0 && (
                        <div>
                          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">
                            Kandidáti podle AI
                          </p>
                          <ul className="space-y-1">
                            {activeClosestData.top_3_candidates.map((cand, idx) => (
                              <li key={cand.id}>
                                <button
                                  type="button"
                                  onClick={() => onSelectPlayer?.(cand.id)}
                                  className="w-full text-left text-[11px] px-2 py-1 rounded-lg bg-slate-950/60 border border-slate-800 text-slate-300 hover:border-amber-500/50 hover:text-amber-200 transition-colors"
                                >
                                  <span className="font-bold text-amber-300/90">{idx + 1}.</span>{' '}
                                  {cand.name}
                                  {cand.why && (
                                    <span className="text-slate-400"> — {cand.why}</span>
                                  )}
                                </button>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                    {/* Alternativy z výpočtu (starší pole) */}
                    {(!activeClosestData?.top_3_candidates ||
                      activeClosestData.top_3_candidates.length === 0) &&
                      activeClosestData?.alternatives &&
                      activeClosestData.alternatives.length > 0 && (
                        <div>
                          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">
                            Další v pořadí
                          </p>
                          <div className="flex flex-wrap gap-1.5">
                            {activeClosestData.alternatives.map((alt) => (
                              <button
                                key={alt.id}
                                type="button"
                                onClick={() => onSelectPlayer?.(alt.id)}
                                className="text-[10px] px-2 py-1 rounded-lg bg-slate-950 border border-slate-800 text-slate-300 hover:border-amber-500/50 hover:text-amber-200 transition-colors"
                              >
                                {alt.full_name} · {alt.match_pct} %
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                  </div>
                )}

                {closest && onSelectPlayer && (
                  <button
                    type="button"
                    onClick={() => onSelectPlayer(closest.id)}
                    className="mt-3 text-xs font-bold text-amber-300 hover:text-amber-200"
                  >
                    Otevřít profil nejbližšího hráče
                  </button>
                )}
              </div>

              {/* Zajímavosti o hráči */}
              <div className="mt-4 pt-4 border-t border-amber-500/20">
                <div className="flex items-center gap-2 text-amber-300 mb-2">
                  <Sparkles className="w-4 h-4" />
                  <span className="text-xs font-bold uppercase tracking-wider">
                    Zajímavosti
                  </span>
                </div>

                {factsLoading && (
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Hledám zajímavosti…
                  </div>
                )}

                {!factsLoading && facts.length === 0 && (
                  <p className="text-xs text-slate-500 italic">
                    K tomuto hráči zatím žádnou zajímavost nemáme.
                  </p>
                )}

                <ul className="space-y-2">
                  {!factsLoading &&
                    facts.map((f) => (
                      <li
                        key={f.id}
                        className="flex gap-3 p-2.5 rounded-xl bg-slate-950/60 border border-slate-800"
                      >
                        <img
                          src={f.headshot_url}
                          alt={f.player}
                          className="w-10 h-10 rounded-full object-cover object-top bg-slate-900 border border-slate-700 shrink-0"
                          onError={(e) => {
                            (e.currentTarget as HTMLImageElement).style.visibility = 'hidden';
                          }}
                        />
                        <div className="min-w-0">
                          <span className="text-[10px] font-black uppercase tracking-wider text-amber-400">
                            {f.category}
                          </span>
                          <p className="text-[11px] text-slate-300 leading-relaxed">{f.text}</p>
                        </div>
                      </li>
                    ))}
                </ul>
              </div>
            </div>

            {/* Rule-based Playstyle Tags calculated from real stats */}
            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-2">
                <Target className="w-4 h-4 text-orange-400" />
                Pravidlově vypočítané tagy herního stylu (z kariérních statistik)
              </h4>
              <div className="flex flex-wrap gap-2">
                {player.playstyle_tags && player.playstyle_tags.length > 0 ? (
                  player.playstyle_tags.map((tag, idx) => (
                    <span
                      key={idx}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-slate-950 border border-orange-500/30 text-orange-300 shadow-sm hover:border-orange-500 transition-colors"
                    >
                      <Zap className="w-3.5 h-3.5 text-amber-400" />
                      {tag}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-slate-500">Žádné tagy k dispozici</span>
                )}
              </div>
            </div>

            {/* Shooting Profile & Zones */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="p-4 rounded-xl bg-slate-950 border border-slate-800">
                <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                  <span>Dvojky (2-Bodová zóna)</span>
                  <Percent className="w-3.5 h-3.5 text-orange-400" />
                </div>
                <div className="text-xl font-bold text-white">
                  {summary ? `${(summary.fg_pct * 100).toFixed(1)}% FG` : '-'}
                </div>
                <p className="text-[11px] text-slate-500 mt-1">
                  Střelba ze střední vzdálenosti a zakončení pod košem
                </p>
              </div>

              <div className="p-4 rounded-xl bg-slate-950 border border-slate-800">
                <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                  <span>Trojky (3-Bodová střelba)</span>
                  <Target className="w-3.5 h-3.5 text-amber-400" />
                </div>
                <div className="text-xl font-bold text-amber-400">
                  {summary ? `${(summary.fg3_pct * 100).toFixed(1)}% 3P` : '-'}
                </div>
                <p className="text-[11px] text-slate-500 mt-1">
                  Efektivita zpoza oblouku v kariéře
                </p>
              </div>

              <div className="p-4 rounded-xl bg-slate-950 border border-slate-800">
                <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                  <span>Trestné hody (FT Line)</span>
                  <Shield className="w-3.5 h-3.5 text-emerald-400" />
                </div>
                <div className="text-xl font-bold text-emerald-400">
                  {summary ? `${(summary.ft_pct * 100).toFixed(1)}% FT` : '-'}
                </div>
                <p className="text-[11px] text-slate-500 mt-1">
                  Úspěšnost proměňování faulů a šestek
                </p>
              </div>
            </div>

            {/* Biographical Summary from Wikipedia API */}
            <div className="p-5 rounded-2xl bg-slate-950 border border-slate-800 space-y-2">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                <BookOpen className="w-4 h-4 text-sky-400" />
                Biografický souhrn (Wikipedia API v češtině)
              </h4>
              <p className="text-xs sm:text-sm text-slate-300 leading-relaxed">
                {player.bio_summary || 'Biografický souhrn není k dispozici.'}
              </p>
              <div className="text-[11px] text-slate-500 pt-1 flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                <span>Uloženo v lokální SQLite cache (nba_vault.db)</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
