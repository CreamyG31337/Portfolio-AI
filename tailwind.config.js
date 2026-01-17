/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./web_dashboard/templates/**/*.html",
    "./web_dashboard/static/**/*.js",
    // Include any Python files that might contain Tailwind classes in strings
    "./web_dashboard/**/*.py",
  ],
  darkMode: ['selector', '[data-theme="dark"], [data-theme="midnight-tokyo"], [data-theme="abyss"]'],
  theme: {
    extend: {
      colors: {
        accent: {
          DEFAULT: 'var(--color-accent)',
          hover: 'var(--color-accent-hover)',
        },
        dashboard: {
          background: 'var(--bg-primary)',
          surface: 'var(--bg-secondary)',
          'surface-alt': 'var(--bg-tertiary)',
        },
        text: {
          primary: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          muted: 'var(--text-muted)',
        },
        border: {
          DEFAULT: 'var(--border-color)',
          hover: 'var(--border-hover)',
        }
      }
    },
  },
  plugins: [
    // Add Tailwind plugins here if needed
    // Example: require('@tailwindcss/typography'),
  ],
}
