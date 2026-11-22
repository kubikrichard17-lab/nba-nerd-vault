'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Loader2,
  Sparkles,
  Trophy,
  RefreshCw,
} from 'lucide-react';
import type { Fact, FactsResponse } from '@/types/facts';
import { API } from '@/lib/api';


const CATEGORY_STYLE: Record<string, string> = {
  Rekord: 'bg-orange-500/20 text-orange-300 border-orange-500/40',
  Trofeje: 'bg-amber-400/20 text-amber-200 border-amber-400/40',
  Příběh: 'bg-sky-500/20 text-sky-300 border-sky-500/40',
};

const shuffle = <T,>(arr: T[]): T[] => {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
};

export default function ZajimavostiPage() {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [index, setIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [imgError, setImgError] = useState<Record<number, boolean>>({});
  const containerRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/facts?shuffle=true`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: FactsResponse = await res.json();
      setFacts(data.facts || []);
      setIndex(0);
      containerRef.current?.scrollTo({ top: 0 });
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'neznámá chyba';
      setError(
        msg.includes('fetch')
          ? 'Backend neběží – spusť START.bat a zkus to znovu.'
          : `Zajímavosti se nepodařilo načíst (${msg}).`,
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const go = useCallback(
    (dir: 1 | -1) => {
      setIndex((prev) => {
        const next = prev + dir;
        if (next < 0 || next >= facts.length) return prev;
        return next;
      });
    },
    [facts.length],
  );

  // ovládání šipkami + mezerníkem
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown' || e.key === 'PageDown' || e.key === ' ') {
        e.preventDefault();
        go(1);
      } else if (e.key === 'ArrowUp' || e.key === 'PageUp') {
        e.preventDefault();
        go(-1);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [go]);

  // swipe (dotyk) + kolečko myši – jedno gesto = jeden fakt
  const touchStart = useRef<number | null>(null);
  const wheelLock = useRef(false);

  const onTouchStart = (e: React.TouchEvent) => {
    touchStart.current = e.touches[0].clientY;
  };
  const onTouchEnd = (e: React.TouchEvent) => {
    if (touchStart.current === null) return;
    const delta = touchStart.current - e.changedTouches[0].clientY;
    touchStart.current = null;
    if (Math.abs(delta) < 45) return;
    go(delta > 0 ? 1 : -1);
  };
  const onWheel = (e: React.WheelEvent) => {
    if (Math.abs(e.deltaY) < 12 || wheelLock.current) return;
    wheelLock.current = true;
    go(e.deltaY > 0 ? 1 : -1);
    window.setTimeout(() => {
      wheelLock.current = false;
    }, 520);
  };

  const fact = facts[index];
  const progress = facts.length ? ((index + 1) / facts.length) * 100 : 0;

  return (
    <main className="max-w-5xl mx-auto px-3 sm:px-6 py-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-black tracking-tight text-white flex items-center gap-2">
            <Sparkles className="w-6 h-6 text-orange-400" />
            Zajímavosti
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Swipuj nahoru nebo dolů · šipky · kolečko myši
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs font-semibold text-slate-300 hover:text-white hover:border-slate-700 disabled:opacity-50 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          <span className="hidden sm:inline">Zamíchat</span>
        </button>
      </div>

      {loading && (
        <div className="flex flex-col items-center justify-center py-28 gap-3 text-slate-400">
          <Loader2 className="w-8 h-8 animate-spin text-orange-400" />
          <span className="text-sm">Načítám zajímavosti…</span>
        </div>
      )}

      {error && !loading && (
        <div className="flex items-start gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {!loading && !error && fact && (
        <div className="relative">
          <div
            ref={containerRef}
            onTouchStart={onTouchStart}
            onTouchEnd={onTouchEnd}
            onWheel={onWheel}
            className="relative rounded-3xl overflow-hidden border border-slate-800 bg-slate-900 select-none"
            style={{ height: 'min(74vh, 760px)' }}
          >
            {/* Fotka hráče */}
            <div className="absolute inset-0">
              {!imgError[fact.player_id] ? (
                <img
                  src={fact.headshot_url}
                  alt={fact.player}
                  onError={() =>
                    setImgError((prev) => ({ ...prev, [fact.player_id]: true }))
                  }
                  className="w-full h-full object-contain object-top scale-105 opacity-95"
                  draggable={false}
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-slate-900 to-slate-950">
                  <Trophy className="w-24 h-24 text-slate-700" />
                </div>
              )}
              <div className="absolute inset-0 bg-gradient-to-t from-slate-950 via-slate-950/70 to-transparent" />
            </div>

            {/* Obsah */}
            <div className="relative h-full flex flex-col justify-end p-5 sm:p-8 gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`px-2.5 py-1 rounded-full text-[11px] font-black uppercase tracking-wider border ${
                    CATEGORY_STYLE[fact.category] || 'bg-slate-800 text-slate-300 border-slate-700'
                  }`}
                >
                  {fact.category}
                </span>
                {fact.bio?.team && (
                  <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-slate-950/70 border border-slate-700 text-slate-300">
                    {fact.bio.team}
                  </span>
                )}
                {fact.bio?.position && (
                  <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-slate-950/70 border border-slate-700 text-slate-400">
                    {fact.bio.position}
                  </span>
                )}
              </div>

              <h2 className="text-2xl sm:text-4xl font-black text-white leading-tight">
                {fact.player}
              </h2>

              <p className="text-sm sm:text-lg text-slate-200 leading-relaxed max-w-2xl">
                {fact.text}
              </p>

              <div className="flex items-center gap-3 text-[11px] text-slate-400 flex-wrap">
                {fact.bio?.from_year ? (
                  <span>
                    v NBA {fact.bio.from_year}–{fact.bio.to_year}
                  </span>
                ) : null}
                {fact.bio?.birthdate ? (
                  <span>nar. {fact.bio.birthdate.split('-').reverse().join('. ')}</span>
                ) : null}
                {fact.bio?.height ? <span>{fact.bio.height}</span> : null}
                <Link
                  href={`/?player=${fact.player_id}`}
                  className="ml-auto font-bold text-orange-300 hover:text-orange-200"
                >
                  Otevřít profil →
                </Link>
              </div>
            </div>

            {/* Ovládání vpravo */}
            <div className="absolute right-3 top-1/2 -translate-y-1/2 flex flex-col gap-2">
              <button
                onClick={() => go(-1)}
                disabled={index === 0}
                className="w-10 h-10 rounded-full bg-slate-950/70 border border-slate-700 text-slate-300 hover:text-white disabled:opacity-30 flex items-center justify-center backdrop-blur"
                aria-label="Předchozí"
              >
                <ChevronUp className="w-5 h-5" />
              </button>
              <button
                onClick={() => go(1)}
                disabled={index >= facts.length - 1}
                className="w-10 h-10 rounded-full bg-slate-950/70 border border-slate-700 text-slate-300 hover:text-white disabled:opacity-30 flex items-center justify-center backdrop-blur"
                aria-label="Další"
              >
                <ChevronDown className="w-5 h-5" />
              </button>
            </div>

            {/* Počítadlo + ukazatel */}
            <div className="absolute top-3 left-0 right-0 flex items-center justify-center gap-3 px-4">
              <div className="flex gap-1">
                {facts.slice(0, 40).map((f, i) => (
                  <span
                    key={f.id}
                    className={`h-1 rounded-full transition-all ${
                      i === index ? 'w-6 bg-white' : 'w-3 bg-white/30'
                    }`}
                  />
                ))}
              </div>
            </div>
            <div className="absolute bottom-2 left-0 right-0 h-0.5 bg-slate-800">
              <div
                className="h-full bg-orange-500 transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>

          <p className="text-center text-[11px] text-slate-500 mt-2">
            {index + 1} / {facts.length} · swipuj pro další zajímavost
          </p>
        </div>
      )}
    </main>
  );
}
