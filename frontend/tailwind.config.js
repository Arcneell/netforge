/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        // Three faces, three jobs. The pairing is by *width*, not by style:
        // Archivo runs expanded for display, Plex Sans runs normal for reading,
        // Plex Mono runs tracked-out for legends.
        //
        // Archivo — display only. Never set it directly; use `.nf-display`,
        // which also pushes the variable `wdth` axis to 118%. That expanded cut
        // is the silkscreen on an equipment front panel, and it is the single
        // most recognisable thing about this interface.
        display: [
          'Archivo Variable',
          'Archivo',
          'ui-sans-serif',
          'Segoe UI',
          'Helvetica',
          'sans-serif',
        ],
        // IBM Plex Sans for the body. Chosen over a neutral grotesque because
        // it was drawn for technical documentation — and because it makes the
        // mono face a sibling rather than a foreign guest.
        sans: [
          'IBM Plex Sans Variable',
          'IBM Plex Sans',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'sans-serif',
        ],
        // Mono is promoted. Beyond code-like values (CIDRs, MACs, firmware) it
        // now carries every legend and column header — see `.nf-legend`.
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

        // The engraved plate. Always the darkest value in the theme — a plate is
        // recessed, so it stays dark whether the page is light or dark. Carries
        // the primary navigation and every label that names a physical thing.
        plate: 'rgb(var(--color-plate) / <alpha-value>)',
        'plate-raised': 'rgb(var(--color-plate-raised) / <alpha-value>)',
        'plate-fg': 'rgb(var(--color-plate-fg) / <alpha-value>)',
        'plate-fg-muted': 'rgb(var(--color-plate-fg-muted) / <alpha-value>)',
        'plate-border': 'rgb(var(--color-plate-border) / <alpha-value>)',

        // Teal — the single brand accent, taken from the jacket colour of OM4
        // multimode patch fibre. Ink, never light: no glow, no neon.
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
        // Panels don't float — they sit flush and catch a line of light on the
        // bottom lip. `xs`/`sm` are that lip, not a drop shadow.
        xs: '0 1px 0 0 rgb(var(--color-border-strong) / 0.38)',
        sm: '0 1px 0 0 rgb(var(--color-border-strong) / 0.55)',
        // Reserved for things that genuinely leave the surface: dropdowns,
        // modals, toasts. Tight and dark rather than wide and soft.
        md: '0 6px 16px -6px rgb(10 14 13 / 0.30)',
        lg: '0 12px 28px -8px rgb(10 14 13 / 0.36)',
        xl: '0 20px 48px -12px rgb(10 14 13 / 0.46)',
        // Recessed: inputs and the search field read as milled slots.
        inset: 'inset 0 1px 2px 0 rgb(10 14 13 / 0.13)',
        // Focus ring drawn as a shadow so it doesn't shift layout.
        ring: '0 0 0 3px rgb(var(--color-primary-500) / 0.30)',
      },
      borderRadius: {
        // Equipment has square corners. 2px is the tool radius of a milled
        // edge, not a decorative round. Where a corner needs to be interesting
        // it gets a 45° chamfer instead — see `.nf-chamfer`.
        DEFAULT: '2px',
        md: '2px' /* inputs, buttons, badges */,
        lg: '3px' /* cards, dropdowns */,
        xl: '4px' /* modals */,
        '2xl': '8px' /* mobile sheets — thumb-friendly, the one exception */,
      },
      fontSize: {
        // Body is 14px; anything smaller is metadata only. Unchanged from the
        // previous scale so table densities across 20+ views stay put.
        '2xs': ['0.6875rem', { lineHeight: '1rem' }] /* 11px */,
        xs: ['0.75rem', { lineHeight: '1.125rem' }] /* 12px */,
        sm: ['0.8125rem', { lineHeight: '1.25rem' }] /* 13px */,
        base: ['0.875rem', { lineHeight: '1.375rem' }] /* 14px */,
        md: ['0.9375rem', { lineHeight: '1.5rem' }] /* 15px */,
        lg: ['1.0625rem', { lineHeight: '1.5rem' }] /* 17px */,
        xl: ['1.25rem', { lineHeight: '1.75rem' }] /* 20px */,
        '2xl': ['1.5rem', { lineHeight: '1.875rem' }] /* 24px — page titles */,
        '3xl': ['1.875rem', { lineHeight: '2.125rem' }] /* 30px */,
        '4xl': ['2.25rem', { lineHeight: '2.375rem' }] /* 36px — hero figures */,
        '5xl': ['3rem', { lineHeight: '3rem' }] /* 48px */,
      },
      transitionTimingFunction: {
        soft: 'cubic-bezier(0.4, 0, 0.2, 1)',
        // Mechanical: fast off the mark, hard stop. A relay, not a spring.
        panel: 'cubic-bezier(0.2, 0.9, 0.25, 1)',
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
          // 0.99, not 0.98: a modal that is visibly the wrong size for a frame
          // reads as elastic, and nothing in this interface is elastic.
          '0%': { opacity: '0', transform: 'scale(0.99)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
      },
      animation: {
        // All three on the panel curve — fast off the mark, hard stop. Overlays
        // and menus arriving with the same mechanical timing as the panels
        // underneath them is most of what makes the motion read as one system.
        'fade-in': 'fade-in 130ms cubic-bezier(0.2, 0.9, 0.25, 1)',
        'slide-up-fade': 'slide-up-fade 150ms cubic-bezier(0.2, 0.9, 0.25, 1)',
        'scale-fade': 'scale-fade 140ms cubic-bezier(0.2, 0.9, 0.25, 1)',
      },
    },
  },
  plugins: [],
}
