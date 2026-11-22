import type { Metadata } from 'next';
import './globals.css';
import { Navbar } from '@/components/Navbar';

export const metadata: Metadata = {
  title: 'NBA Nerd Vault – Analýza & Porovnávání hráčů NBA',
  description: 'Webová aplikace pro podrobnou statistickou analýzu hráčů NBA s databázovou cache, matematickým similarity enginem a AI scoutingem v češtině.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="cs" className="dark">
      <body className="bg-slate-950 text-slate-100 min-h-screen flex flex-col font-sans antialiased selection:bg-orange-500 selection:text-white">
        <Navbar />
        <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
          {children}
        </main>
        <footer className="border-t border-slate-900 bg-slate-950/80 py-6 text-center text-xs text-slate-500">
          <div className="max-w-7xl mx-auto px-4">
            <span className="font-semibold text-slate-400">NBA Nerd Vault</span> (Fáze 1 – Modulární architektura) • Data z nba_api & Wikipedia API • Lokální SQLite cache
          </div>
        </footer>
      </body>
    </html>
  );
}
