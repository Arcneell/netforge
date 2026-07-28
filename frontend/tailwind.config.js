/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        // Inter for the whole interface. One variable file, and its tall
        // x-height keeps 13-14px UI text legible at the densities this app
        // reaches in tables.
        sans: [
          'Inter Variable',
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'sans-serif',
        ],
        // Reserved for values that are genuinely code-like: CIDRs, MACs,
        // firmware strings. Not a decorative choice — it exists so 0 and O
        // never trade places in an IP address.
        mono: ['IBM Plex Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      colors: {
        // Semantic tokens — values resolved from CSS variables in tailwind.css,
        // so the same class works in light and dark without a `dark:` prefix.
        bg: 'rgb(var(--color-bg) / <alpha-value>)',
        surface: 'rgb(var(--color-surface) / <alpha-value>)',
        'surface-hover': 'rgb(var(--color-surface-hover) / <alpha-value>)',
        border: 'rgb(var(--color-border) / <alpha-value>)',
        'border-strong': 'rgb(var(--color-border-strong) / <alpha-value>)',
        muted: 'rgb(var(--color-muted) / <alpha-value>)',
        fg: 'rgb(var(--color-fg) / <alpha-value>)',
        'fg-muted': 'rgb(var(--color-fg-muted) / <alpha-value>)',
        'fg-subtle': 'rgb(var(--color-fg-subtle) / <alpha-value>)',
        primary: {
          50: 'rgb(var(--color-primary-50) / <alpha-value>)',
          100: 'rgb(var(--color-primary-100) / <alpha-value>)',
          200: 'rgb(var(--color-primary-200) / <alpha-value>)',
          300: 'rgb(var(--color-primary-300) / <alpha-value>)',
          400: 'rgb(var(--color-primary-400) / <alpha-value>)',
          500: 'rgb(var(--color-primary-500) / <alpha-value>)',
          600: 'rgb(var(--color-primary-600) / <alpha-value>)',
          700: 'rgb(var(--color-primary-700) / <alpha-value>)',
          800: 'rgb(var(--color-primary-800) / <alpha-value>)',
          900: 'rgb(var(--color-primary-900) / <alpha-value>)',
          950: 'rgb(var(--color-primary-950) / <alpha-value>)',
        },
        success: 'rgb(var(--color-success) / <alpha-value>)',
        warning: 'rgb(var(--color-warning) / <alpha-value>)',
        danger: 'rgb(var(--color-danger) / <alpha-value>)',
      },
      boxShadow: {
        // Restraint: elevation only where something genuinely floats.
        xs: '0 1px 2px 0 rgb(16 24 40 / 0.04)',
        sm: '0 1px 2px 0 rgb(16 24 40 / 0.06), 0 1px 3px 0 rgb(16 24 40 / 0.04)',
        md: '0 2px 4px -2px rgb(16 24 40 / 0.06), 0 4px 12px -2px rgb(16 24 40 / 0.08)',
        lg: '0 4px 6px -2px rgb(16 24 40 / 0.05), 0 12px 24px -4px rgb(16 24 40 / 0.10)',
        xl: '0 8px 8px -4px rgb(16 24 40 / 0.04), 0 20px 40px -8px rgb(16 24 40 / 0.14)',
        // Focus ring drawn as a shadow so it doesn't shift layout.
        ring: '0 0 0 3px rgb(var(--color-primary-500) / 0.16)',
      },
      borderRadius: {
        DEFAULT: '0.375rem' /* 6px */,
        md: '0.375rem' /* 6px  — inputs, buttons, badges */,
        lg: '0.625rem' /* 10px — cards, dropdowns */,
        xl: '0.75rem' /* 12px — modals */,
        '2xl': '1rem' /* 16px — mobile sheets */,
      },
      fontSize: {
        // Deliberate scale. Body is 14px; anything smaller is metadata only.
        '2xs': ['0.6875rem', { lineHeight: '1rem' }] /* 11px */,
        xs: ['0.75rem', { lineHeight: '1.125rem' }] /* 12px */,
        sm: ['0.8125rem', { lineHeight: '1.25rem' }] /* 13px */,
        base: ['0.875rem', { lineHeight: '1.375rem' }] /* 14px */,
        md: ['0.9375rem', { lineHeight: '1.5rem' }] /* 15px */,
        lg: ['1.0625rem', { lineHeight: '1.5rem' }] /* 17px */,
        xl: ['1.25rem', { lineHeight: '1.75rem' }] /* 20px */,
        '2xl': ['1.5rem', { lineHeight: '2rem' }] /* 24px — page titles */,
        '3xl': ['1.875rem', { lineHeight: '2.25rem' }] /* 30px */,
        '4xl': ['2.25rem', { lineHeight: '2.5rem' }] /* 36px — hero figures */,
      },
      transitionTimingFunction: {
        soft: 'cubic-bezier(0.4, 0, 0.2, 1)',
      },
      keyframes: {
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'slide-up-fade': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'scale-fade': {
          '0%': { opacity: '0', transform: 'scale(0.98)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 150ms cubic-bezier(0.4, 0, 0.2, 1)',
        'slide-up-fade': 'slide-up-fade 160ms cubic-bezier(0.4, 0, 0.2, 1)',
        'scale-fade': 'scale-fade 150ms cubic-bezier(0.4, 0, 0.2, 1)',
      },
    },
  },
  plugins: [],
}
