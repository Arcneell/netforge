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
        // iOS-flavoured elevation. Cards barely lift; modals get a richer
        // stack with a dual-shadow that hugs the corners like Apple's
        // "Card" style in HIG. The 1-px inner ring on `pop` keeps modal
        // edges crisp on the lighter scrim.
        card: '0 1px 2px -1px rgb(15 23 42 / 0.04), 0 2px 8px -2px rgb(15 23 42 / 0.04)',
        'card-hover': '0 1px 3px -1px rgb(15 23 42 / 0.06), 0 8px 20px -6px rgb(15 23 42 / 0.10)',
        pop: '0 0 0 1px rgb(15 23 42 / 0.04), 0 12px 28px -8px rgb(15 23 42 / 0.18), 0 32px 64px -32px rgb(15 23 42 / 0.20)',
        glow: '0 0 0 1px rgb(var(--color-primary-500) / 0.4), 0 6px 16px -4px rgb(var(--color-primary-500) / 0.30)',
        // Subtle inset highlight used on iOS-style stat cards to give them
        // that "glass tile" feel — pure cosmetic, optional.
        'inner-top': 'inset 0 1px 0 0 rgb(255 255 255 / 0.6)',
      },
      borderRadius: {
        // Bumped across the board. iOS leans heavy on rounded corners — a
        // 14-px card looks much more "Apple" than an 8-px one. Inputs and
        // buttons keep moderate rounding so they don't look like pills next
        // to their labels.
        DEFAULT: '0.625rem' /* 10px */,
        md: '0.625rem' /* 10px — inputs, small buttons */,
        lg: '0.875rem' /* 14px — cards, dropdowns */,
        xl: '1.125rem' /* 18px — modals, sheets */,
        '2xl': '1.5rem' /* 24px — hero panels */,
      },
      transitionTimingFunction: {
        // iOS-flavoured spring-ish ease. Slightly bouncier on the way in,
        // gentle on the way out — matches the "settles into place" feel.
        'out-quad': 'cubic-bezier(0.25, 0.46, 0.45, 0.94)',
        'ios-spring': 'cubic-bezier(0.34, 1.56, 0.64, 1)',
      },
      keyframes: {
        'slide-up-fade': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'scale-fade': {
          '0%': { opacity: '0', transform: 'scale(0.96)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
      },
      animation: {
        'slide-up-fade': 'slide-up-fade 200ms cubic-bezier(0.25, 0.46, 0.45, 0.94)',
        'scale-fade': 'scale-fade 180ms cubic-bezier(0.34, 1.56, 0.64, 1)',
      },
    },
  },
  plugins: [],
}
