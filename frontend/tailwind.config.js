/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        // Geist Sans for the UI; system fallback chain matches what the
        // self-hosted @fontsource bundle expects.
        sans: [
          'Geist Sans',
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'sans-serif',
        ],
        // Geist Mono for technical values (IDs, CIDRs, MACs). JetBrains Mono
        // stays in the fallback chain so deployments without Geist Mono get a
        // sane similar-feel monospace.
        mono: [
          'Geist Mono',
          'JetBrains Mono',
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'monospace',
        ],
      },
      colors: {
        // Semantic tokens — values resolved from CSS variables in tailwind.css.
        // Lets the same class work in both light and dark mode without `dark:` prefixes.
        bg: 'rgb(var(--color-bg) / <alpha-value>)',
        surface: 'rgb(var(--color-surface) / <alpha-value>)',
        'surface-hover': 'rgb(var(--color-surface-hover) / <alpha-value>)',
        border: 'rgb(var(--color-border) / <alpha-value>)',
        muted: 'rgb(var(--color-muted) / <alpha-value>)',
        fg: 'rgb(var(--color-fg) / <alpha-value>)',
        'fg-muted': 'rgb(var(--color-fg-muted) / <alpha-value>)',
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
        // Cards : 1px hairline + a very soft drop. Reads as elevated paper
        // rather than a floating panel — fits the dense layout.
        card: '0 1px 2px 0 rgb(0 0 0 / 0.04), 0 1px 3px 0 rgb(0 0 0 / 0.06)',
        // Pop-overs (modals, command palette). The inner ring keeps the edge
        // crisp on dark backgrounds where pure shadow would disappear.
        pop: '0 0 0 1px rgb(0 0 0 / 0.04), 0 12px 32px -8px rgb(0 0 0 / 0.20)',
        // Focus state for explicit "selected" affordances — used by Button's
        // primary variant on hover and by the active sidebar row.
        glow: '0 0 0 1px rgb(var(--color-primary-500) / 0.4), 0 4px 12px -2px rgb(var(--color-primary-500) / 0.18)',
      },
      borderRadius: {
        DEFAULT: '0.5rem',
        md: '0.5rem' /* 8px — primary radius for cards/inputs */,
        lg: '0.625rem' /* 10px — modals, dropdowns */,
        xl: '0.875rem' /* 14px — page-level panels */,
      },
      transitionTimingFunction: {
        // Sharper-than-default ease. The standard tailwind ease feels syrupy
        // on a dense UI; this matches what shadcn/radix uses for menus.
        'out-quad': 'cubic-bezier(0.25, 0.46, 0.45, 0.94)',
      },
      keyframes: {
        // Subtle slide-in for toast / dropdown surfaces.
        'slide-up-fade': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'slide-up-fade': 'slide-up-fade 150ms cubic-bezier(0.25, 0.46, 0.45, 0.94)',
      },
    },
  },
  plugins: [],
}
