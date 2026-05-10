/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  'var(--brand-50)',
          100: 'var(--brand-100)',
          200: 'var(--brand-200)',
          400: 'var(--brand-400)',
          600: 'var(--brand-600)',
          800: 'var(--brand-800)',
          900: 'var(--brand-900)',
        },
        amber: {
          50: '#FAEEDA', 200: '#EF9F27', 400: '#BA7517', 600: '#854F0B',
        },
        danger: { 400: '#E24B4A', 600: '#A32D2D' },
        info: { 400: '#378ADD' },
        surface: 'var(--surface)',
        page:    'var(--page)',
      },
      fontFamily: {
        display: ['"Space Grotesk"', 'sans-serif'],
        body:    ['"Plus Jakarta Sans"', 'sans-serif'],
        mono:    ['"JetBrains Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
}
