'use client';

import React, { useState, useEffect } from 'react';
import { CompareResponse, StyleCompareResult } from '@/types';
import { CompareRadar } from '@/components/CompareRadar';
import { ComparePlayerSearch } from '@/components/ComparePlayerSearch';
import {
  GitCompare,
  Sparkles,
  Scale,
  Brain,
  TrendingUp,
  Percent,
  CheckCircle2,
  Loader2,
  Calendar,
  Users
} from 'lucide-react';
import { API } from '@/lib/api';

export default function ComparePage() {
  const [p1Id, setP1Id] = useState<number>(893); // Michael Jordan
  const [p2Id, setP2Id] = useState<number>(977); // Kobe Bryant
  const [p1Season, setP1Season] = useState<string>('prime');
  const [p2Season, setP2Season] = useState<string>('prime');

  const [compareData, setCompareData] = useState<CompareResponse | null>(null);
  const style: StyleCompareResult | null = compareData?.style ?? null;
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const runComparison = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/compare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          p1_id: p1Id,
          p2_id: p2Id,
          season1: p1Season,
          season2: p2Season,
        }),
      });

      if (!res.ok) {
        throw new Error('Chyba při porovnávání hráčů ze serveru.');
      }

      const data = await res.json();
      setCompareData(data);

    } catch (err: any) {
      console.error(err);
      setError(err.message || 'Chyba připojení k backendu.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    runComparison();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p1Id, p2Id, p1Season, p2Season]);

  // Color badge for match score
  const getMatchBadgeColor = (pct: number) => {
    if (pct >= 80) return 'from-emerald-500 to-green-600 text-white';
    if (pct >= 60) return 'from-amber-500 to-orange-600 text-white';
    return 'from-sky-500 to-indigo-600 text-white';
  };

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="text-center space-y-2 max-w-3xl mx-auto">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-orange-500/10 text-orange-400 border border-orange-500/20 text-xs font-bold uppercase tracking-wider">
          <GitCompare className="w-3.5 h-3.5" /> All-Time Porovnávač
        </div>
        <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-white">
          Matematické srovnání &amp; AI Analýza
        </h1>
        <p className="text-sm sm:text-base text-slate-400">
          Porovnej libovolné dvě legendy nebo současné hráče NBA. Similarity Engine kombinuje normalizované statistiky na 100 držení míče (Cosine Similarity), fyzickou stavbu a herní styl.
        </p>
      </div>

      {/* Selectors Bar */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 bg-slate-900/90 border border-slate-800 p-4 sm:p-6 rounded-2xl shadow-xl">
        {/* Player 1 Box */}
        <div className="space-y-3 p-4 rounded-xl bg-slate-950/80 border border-orange-500/30">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-orange-400 uppercase tracking-wider flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-orange-500" /> Hráč 1
            </span>
            {compareData && (
              <span className="text-xs text-slate-400">
                {compareData.player1.position} • {compareData.player1.height_cm} cm
              </span>
            )}
          </div>

          <div className="space-y-2">
            <ComparePlayerSearch
              label="Hráč 1"
              color="orange"
              selectedPlayer={compareData?.player1 ?? null}
              onSelectPlayer={(id) => {
                setP1Id(id);
                setP1Season('prime');
              }}
            />

            {/* Season 1 Selector */}
            {compareData && (
              <div className="flex items-center gap-2 text-xs">
                <Calendar className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                <span className="text-slate-400">Období:</span>
                <select
                  value={p1Season}
                  onChange={(e) => setP1Season(e.target.value)}
                  className="bg-slate-900 border border-slate-700/80 rounded-lg px-2 py-1 text-slate-200 text-xs focus:outline-none focus:ring-1 focus:ring-orange-500 flex-1"
                >
                  {compareData.player1.available_seasons.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>

        {/* Player 2 Box */}
        <div className="space-y-3 p-4 rounded-xl bg-slate-950/80 border border-sky-500/30">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-sky-400 uppercase tracking-wider flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-sky-500" /> Hráč 2
            </span>
            {compareData && (
              <span className="text-xs text-slate-400">
                {compareData.player2.position} • {compareData.player2.height_cm} cm
              </span>
            )}
          </div>

          <div className="space-y-2">
            <ComparePlayerSearch
              label="Hráč 2"
              color="sky"
              selectedPlayer={compareData?.player2 ?? null}
              onSelectPlayer={(id) => {
                setP2Id(id);
                setP2Season('prime');
              }}
            />

            {/* Season 2 Selector */}
            {compareData && (
              <div className="flex items-center gap-2 text-xs">
                <Calendar className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                <span className="text-slate-400">Období:</span>
                <select
                  value={p2Season}
                  onChange={(e) => setP2Season(e.target.value)}
                  className="bg-slate-900 border border-slate-700/80 rounded-lg px-2 py-1 text-slate-200 text-xs focus:outline-none focus:ring-1 focus:ring-sky-500 flex-1"
                >
                  {compareData.player2.available_seasons.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex flex-col items-center justify-center p-16 space-y-3 bg-slate-900/40 rounded-2xl border border-slate-800">
          <Loader2 className="w-10 h-10 animate-spin text-orange-500" />
          <p className="text-sm font-semibold text-slate-300">
            Počítám Cosine Similarity a generuji AI srovnání...
          </p>
        </div>
      )}

      {/* Error state */}
      {!isLoading && error && (
        <div className="p-6 rounded-2xl bg-red-900/20 border border-red-700/50 text-red-300 text-sm text-center">
          {error}
        </div>
      )}

      {/* Results View */}
      {!isLoading && compareData && (
        <div className="space-y-8">
          {/* Main Similarity Scoreboard Card */}
          <div className="p-6 sm:p-8 rounded-3xl bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 border border-slate-800 shadow-2xl relative overflow-hidden">
            <div className="flex flex-col md:flex-row items-center justify-between gap-6">
              {/* Overall Match Circle */}
              <div className="flex flex-col items-center text-center">
                <span className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-2">
                  Celková shoda hráčů
                </span>
                <div
                  className={`w-32 h-32 rounded-3xl bg-gradient-to-tr ${getMatchBadgeColor(
                    compareData.match_pct
                  )} p-1 shadow-2xl shadow-orange-500/20 flex flex-col items-center justify-center`}
                >
                  <span className="text-4xl font-black tracking-tight">
                    {compareData.match_pct}%
                  </span>
                  <span className="text-[10px] font-bold uppercase tracking-wider opacity-90">
                    stejný model jako hlavní stránka
                  </span>
                </div>
              </div>

              {/* 3 Sub-matches breakdown */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 flex-1 w-full">
                {/* 1. Fyzická shoda */}
                <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800 text-center">
                  <div className="flex items-center justify-center gap-1.5 text-xs text-slate-400 mb-1">
                    <Scale className="w-3.5 h-3.5 text-orange-400" />
                    <span>Fyzická shoda</span>
                  </div>
                  <div className="text-2xl font-black text-white">
                    {compareData.physical_pct}%
                  </div>
                  <div className="text-[10px] text-slate-500 mt-0.5">Výška, váha &amp; typ postavy</div>
                </div>

                {/* 2. Statistická shoda */}
                <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800 text-center">
                  <div className="flex items-center justify-center gap-1.5 text-xs text-slate-400 mb-1">
                    <Brain className="w-3.5 h-3.5 text-emerald-400" />
                    <span>Statistická shoda</span>
                  </div>
                  <div className="text-2xl font-black text-emerald-400">
                    {compareData.statistical_pct}%
                  </div>
                  <div className="text-[10px] text-slate-500 mt-0.5">
                    Odkud hráči skórují
                  </div>
                </div>

                {/* 3. Stylistická shoda */}
                <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800 text-center">
                  <div className="flex items-center justify-center gap-1.5 text-xs text-slate-400 mb-1">
                    <TrendingUp className="w-3.5 h-3.5 text-sky-400" />
                    <span>Stylistická shoda</span>
                  </div>
                  <div className="text-2xl font-black text-sky-400">
                    {compareData.stylistic_pct}%
                  </div>
                  <div className="text-[10px] text-slate-500 mt-0.5">
                    Archetyp &amp; pozice
                  </div>
                </div>
              </div>
            </div>

            {/* Stejný model jako „nejbližší hráč" – archetyp a styl hry */}
            {style && (
              <div className="mt-6 p-5 rounded-2xl bg-slate-950/70 border border-slate-800">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
                  <div className="flex items-center gap-2 text-orange-400">
                    <Users className="w-4 h-4" />
                    <span className="text-xs font-bold uppercase tracking-wider">
                      Podobnost podle stylu hry
                    </span>
                  </div>
                  <span className="text-[11px] text-slate-500">
                    Stejný model jako „nejbližší hráč" na hlavní stránce (v{style.engine_version})
                  </span>
                </div>

                <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-4">
                  <div className="flex-1 w-full p-3 rounded-xl bg-slate-900/70 border border-slate-800 text-center">
                    <div className="text-sm font-bold text-white">{style.player1.full_name}</div>
                    <div className="text-xs text-orange-300 mt-0.5">{style.player1.archetype}</div>
                    <div className="text-[10px] text-slate-500">{style.player1.position}</div>
                  </div>
                  <div className="text-center shrink-0">
                    <div className="text-3xl font-black text-orange-400">{style.match_pct}%</div>
                    <div className="text-[10px] uppercase tracking-wider text-slate-500">
                      styl hry
                    </div>
                  </div>
                  <div className="flex-1 w-full p-3 rounded-xl bg-slate-900/70 border border-slate-800 text-center">
                    <div className="text-sm font-bold text-white">{style.player2.full_name}</div>
                    <div className="text-xs text-orange-300 mt-0.5">{style.player2.archetype}</div>
                    <div className="text-[10px] text-slate-500">{style.player2.position}</div>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-3 mb-3">
                  <div className="p-2.5 rounded-xl bg-slate-900/60 border border-slate-800 text-center">
                    <div className="text-[10px] uppercase tracking-wider text-slate-500">Styl</div>
                    <div className="text-lg font-black text-white">{style.style_pct}%</div>
                  </div>
                  <div className="p-2.5 rounded-xl bg-slate-900/60 border border-slate-800 text-center">
                    <div className="text-[10px] uppercase tracking-wider text-slate-500">Postava</div>
                    <div className="text-lg font-black text-white">{style.physical_pct}%</div>
                  </div>
                  <div className="p-2.5 rounded-xl bg-slate-900/60 border border-slate-800 text-center">
                    <div className="text-[10px] uppercase tracking-wider text-slate-500">Statistiky</div>
                    <div className="text-lg font-black text-white">{style.stats_pct}%</div>
                  </div>
                </div>

                <p className="text-xs text-slate-300 leading-relaxed bg-slate-900/50 p-3 rounded-xl border border-slate-800">
                  {style.style_note}
                </p>
                <p className="text-[10px] text-slate-500 mt-2">
                  Odkud hráč skóruje – podíl bodů z trojek:{' '}
                  {Math.round((style.player1.three_pts_share ?? 0) * 100)} % vs{' '}
                  {Math.round((style.player2.three_pts_share ?? 0) * 100)} %, ze šestek:{' '}
                  {Math.round((style.player1.ft_pts_share ?? 0) * 100)} % vs{' '}
                  {Math.round((style.player2.ft_pts_share ?? 0) * 100)} %.
                </p>
              </div>
            )}

            {/* AI Verdict Box */}
            <div className="mt-6 pt-6 border-t border-slate-800/80">
              <div className="flex items-center gap-2 text-amber-400 mb-2">
                <Sparkles className="w-4 h-4" />
                <span className="text-xs font-bold uppercase tracking-wider">
                  Analytické shrnutí srovnání
                </span>
              </div>
              <p className="text-sm sm:text-base text-slate-200 leading-relaxed font-serif italic bg-slate-950/70 p-4 rounded-2xl border border-slate-800/60">
                &ldquo;{compareData.ai_verdict}&rdquo;
              </p>
            </div>
          </div>

          {/* Visual Grid: Overlay Radar Chart + Detailed Table */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            {/* Left: Radar Chart */}
            <div className="lg:col-span-5 bg-slate-900/90 border border-slate-800 rounded-2xl p-4 sm:p-6 shadow-xl">
              <h3 className="text-sm font-bold uppercase tracking-wider text-slate-300 mb-3 flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-orange-400" />
                Překryvný radarový graf dovedností
              </h3>
              <p className="text-xs text-slate-400 mb-4">
                Srovnání obou hráčů přes sebe v 7 klíčových dimenzích výkonu (škála 0–100 bodů).
              </p>

              <CompareRadar
                data={compareData.radar}
                p1Name={compareData.player1.full_name}
                p2Name={compareData.player2.full_name}
              />
            </div>

            {/* Right: Comparative Metrics Table */}
            <div className="lg:col-span-7 bg-slate-900/90 border border-slate-800 rounded-2xl p-4 sm:p-6 shadow-xl overflow-hidden">
              <h3 className="text-sm font-bold uppercase tracking-wider text-slate-300 mb-3 flex items-center gap-2">
                <Percent className="w-4 h-4 text-sky-400" />
                Srovnávací tabulka hodnot &amp; rozdílů
              </h3>
              <p className="text-xs text-slate-400 mb-4">
                Porovnání fyzických rozměrů, tradičních průměrů i normalizovaných hodnot na 100 držení míče.
              </p>

              <div className="overflow-x-auto rounded-xl border border-slate-800">
                <table className="w-full text-xs text-left">
                  <thead>
                    <tr className="bg-slate-950 text-slate-400 font-semibold border-b border-slate-800 text-[11px] uppercase tracking-wider">
                      <th className="py-2.5 px-3">Metrika</th>
                      <th className="py-2.5 px-3 text-right text-orange-400">
                        {compareData.player1.full_name}
                      </th>
                      <th className="py-2.5 px-3 text-right text-sky-400">
                        {compareData.player2.full_name}
                      </th>
                      <th className="py-2.5 px-3 text-right">Rozdíl (Δ)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 text-slate-200">
                    {compareData.table.map((row, i) => (
                      <tr key={i} className="hover:bg-slate-950/40 transition-colors">
                        <td className="py-2 px-3 font-medium text-slate-300">
                          {row.metric}
                        </td>
                        <td className="py-2 px-3 text-right font-semibold text-white">
                          {row.p1}
                        </td>
                        <td className="py-2 px-3 text-right font-semibold text-white">
                          {row.p2}
                        </td>
                        <td className="py-2 px-3 text-right font-mono font-bold text-slate-300">
                          {typeof row.diff === 'number' ? (
                            <span
                              className={
                                row.diff > 0
                                  ? 'text-orange-400'
                                  : row.diff < 0
                                  ? 'text-sky-400'
                                  : 'text-slate-500'
                              }
                            >
                              {row.diff > 0 ? `+${row.diff}` : row.diff}
                            </span>
                          ) : (
                            row.diff
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
