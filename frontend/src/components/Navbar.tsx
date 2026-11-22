'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Flame, GitCompare, Database, Trophy, Newspaper, BarChart3, ListOrdered, Sparkles } from 'lucide-react';

export const Navbar: React.FC = () => {
  const pathname = usePathname();

  const navItems = [
    { href: '/', label: 'Profil hráče', icon: Flame },
    { href: '/compare', label: 'Porovnávač', icon: GitCompare },
    { href: '/novinky', label: 'Novinky', icon: Newspaper },
    { href: '/lideri', label: 'Lídři', icon: BarChart3 },
    { href: '/tabulka', label: 'Tabulka', icon: ListOrdered },
    { href: '/zajimavosti', label: 'Zajímavosti', icon: Sparkles },
  ];

  return (
    <header className="sticky top-0 z-50 bg-slate-950/80 backdrop-blur-md border-b border-slate-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link href="/" className="flex items-center space-x-3 group">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-amber-600 to-orange-500 flex items-center justify-center shadow-lg shadow-orange-500/20 group-hover:scale-105 transition-transform">
              <Trophy className="w-5 h-5 text-white" />
            </div>
            <div>
              <span className="text-xl font-black tracking-wider bg-gradient-to-r from-white via-slate-100 to-orange-400 bg-clip-text text-transparent">
                NBA NERD VAULT
              </span>
              <span className="ml-2 px-1.5 py-0.5 text-[10px] font-bold bg-orange-500/20 text-orange-400 border border-orange-500/30 rounded uppercase tracking-widest">
                Fáze 1
              </span>
            </div>
          </Link>

          {/* Navigation Links */}
          <nav className="flex space-x-1 sm:space-x-1.5 overflow-x-auto">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center space-x-2 px-2.5 sm:px-3.5 py-2 rounded-lg text-xs sm:text-sm font-semibold transition-all duration-200 whitespace-nowrap ${
                    isActive
                      ? 'bg-orange-500 text-white shadow-md shadow-orange-500/25'
                      : 'text-slate-400 hover:text-white hover:bg-slate-900'
                  }`}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span className="hidden sm:inline">{item.label}</span>
                </Link>
              );
            })}
          </nav>

          {/* Status Badge */}
          <div className="hidden md:flex items-center space-x-2 px-2.5 py-1 rounded-full bg-slate-900 border border-slate-800 text-xs text-slate-400">
            <Database className="w-3.5 h-3.5 text-emerald-400" />
            <span>SQLite Cache:</span>
            <span className="text-emerald-400 font-semibold">Aktivní</span>
          </div>
        </div>
      </div>
    </header>
  );
};
