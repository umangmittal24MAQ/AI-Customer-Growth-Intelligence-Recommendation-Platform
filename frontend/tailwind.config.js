/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: { sans: ['Plus Jakarta Sans', 'DM Sans', 'system-ui', 'sans-serif'] },
      borderRadius: { xl: '1rem', '2xl': '1.25rem' },
      boxShadow: {
        card: '0 1px 3px 0 rgb(0 0 0/0.04), 0 1px 2px -1px rgb(0 0 0/0.04)',
        elevated: '0 4px 6px -1px rgb(0 0 0/0.07), 0 2px 4px -2px rgb(0 0 0/0.05)',
        glass: '0 8px 32px 0 rgba(31,38,135,0.07)',
      },
      animation: {
        'fade-in': 'fadeIn .35s ease-out',
        'slide-up': 'slideUp .4s ease-out',
      },
      keyframes: {
        fadeIn:  { from: { opacity: 0 }, to: { opacity: 1 } },
        slideUp: { from: { opacity: 0, transform: 'translateY(12px)' }, to: { opacity: 1, transform: 'translateY(0)' } },
      },
    },
  },
  plugins: [],
}
