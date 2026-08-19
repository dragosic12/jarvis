/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        jarvis: {
          primary: '#6366f1',
          dark: '#0f0f23',
          card: '#1a1a2e',
          accent: '#22d3ee',
          success: '#22c55e',
          danger: '#ef4444',
          muted: '#64748b',
        }
      }
    },
  },
  plugins: [],
}
