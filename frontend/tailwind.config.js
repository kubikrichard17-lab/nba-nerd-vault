/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        vault: {
          dark: '#080c14',
          card: '#0f172a',
          cardBorder: '#1e293b',
          accent: '#f97316', // basketball orange
          gold: '#eab308',
          blue: '#3b82f6',
          green: '#10b981',
          crimson: '#ef4444'
        }
      }
    },
  },
  plugins: [],
};
