/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#E1F5EE', 100: '#9FE1CB', 200: '#5DCAA5',
          400: '#1D9E75', 600: '#0F6E56', 800: '#085041', 900: '#04342C',
        },
        amber: {
          50: '#FAEEDA', 200: '#EF9F27', 400: '#BA7517', 600: '#854F0B',
        },
        danger: { 400: '#E24B4A', 600: '#A32D2D' },
        info: { 400: '#378ADD' },
        surface: '#F1EFE8',
        page: '#FAFAF8',
      },
      fontFamily: {
        display: ['"Space Grotesk"', 'sans-serif'],
        body: ['"Plus Jakarta Sans"', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
}
