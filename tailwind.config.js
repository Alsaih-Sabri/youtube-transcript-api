/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    "./templates/**/*.html",
    "./static/**/*.js"
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          400: '#fb7185',
          500: '#f43f5e',
          600: '#e11d48',
          700: '#be123c',
        },
        glass: {
          card: 'rgba(255, 255, 255, 0.04)',
          cardHover: 'rgba(255, 255, 255, 0.08)',
          border: 'rgba(255, 255, 255, 0.12)',
          input: 'rgba(0, 0, 0, 0.35)',
        }
      },
      boxShadow: {
        'ios-glass': '0 16px 40px 0 rgba(0, 0, 0, 0.45), inset 0 1px 1px 0 rgba(255, 255, 255, 0.16)',
        'ios-card': '0 8px 32px 0 rgba(0, 0, 0, 0.37), inset 0 1px 1px 0 rgba(255, 255, 255, 0.12)',
        'ios-btn': '0 4px 20px 0 rgba(225, 29, 72, 0.4), inset 0 1px 1px 0 rgba(255, 255, 255, 0.35)',
        'ios-pill': '0 4px 16px 0 rgba(0, 0, 0, 0.25), inset 0 1px 1px 0 rgba(255, 255, 255, 0.2)',
      }
    },
  },
  plugins: [],
}
