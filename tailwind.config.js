/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/renderer/src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ivory: {
          DEFAULT: '#F7F4EE',
          dark:    '#EDE9E0',
          darker:  '#E2DDD3',
        }
      }
    }
  },
  plugins: [],
}
