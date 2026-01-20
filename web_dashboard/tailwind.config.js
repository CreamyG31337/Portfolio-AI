/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
        "./templates/**/*.html",
        "./static/**/*.js",
        "./node_modules/flowbite/**/*.js"
    ],
    theme: {
        extend: {
            colors: {
                // Semantic color names that map to CSS variables
                'dashboard': {
                    'background': 'var(--bg-secondary)',
                    'surface': 'var(--bg-primary)',
                    'surface-alt': 'var(--bg-tertiary)',
                },
                'text': {
                    'primary': 'var(--text-primary)',
                    'secondary': 'var(--text-secondary)',
                    'tertiary': 'var(--text-tertiary)',
                },
                'accent': {
                    'DEFAULT': 'var(--color-accent)',
                    'hover': 'var(--color-accent-hover)',
                    'from': 'var(--gradient-from)',
                    'to': 'var(--gradient-to)',
                },
                'border': {
                    'DEFAULT': 'var(--border-color)',
                    'hover': 'var(--border-hover)',
                },
                // Semantic status colors
                'theme-success': {
                    'bg': 'var(--color-success-bg)',
                    'text': 'var(--color-success-text)',
                },
                'theme-error': {
                    'bg': 'var(--color-error-bg)',
                    'text': 'var(--color-error-text)',
                },
                'theme-warning': {
                    'bg': 'var(--color-warning-bg)',
                    'text': 'var(--color-warning-text)',
                },
                'theme-info': {
                    'bg': 'var(--color-info-bg)',
                    'text': 'var(--color-info-text)',
                },
                // Log level colors
                'log': {
                    'debug': 'var(--log-debug)',
                    'perf': 'var(--log-perf)',
                    'info': 'var(--log-info)',
                    'warning': 'var(--log-warning)',
                    'error': 'var(--log-error)',
                },
                // Component-specific colors
                'code': {
                    'bg': 'var(--code-bg)',
                    'border': 'var(--code-border)',
                },
            },
        },
    },
    plugins: [
        require('flowbite/plugin')
    ],
}
