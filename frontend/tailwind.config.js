/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // CSS-variable-backed so opacity modifiers (e.g. bg-accent/10) still
        // work via Tailwind's rgb(var(--x) / <alpha-value>) convention --
        // values themselves live in globals.css's :root block.
        bg: "rgb(var(--color-bg) / <alpha-value>)",
        surface: "rgb(var(--color-surface) / <alpha-value>)",
        border: "rgb(var(--color-border) / <alpha-value>)",
        "text-primary": "rgb(var(--color-text-primary) / <alpha-value>)",
        "text-muted": "rgb(var(--color-text-muted) / <alpha-value>)",
        accent: {
          DEFAULT: "rgb(var(--color-accent) / <alpha-value>)",
          hover: "rgb(var(--color-accent-hover) / <alpha-value>)",
          subtle: "rgb(var(--color-accent-subtle) / <alpha-value>)",
        },
        positive: {
          DEFAULT: "rgb(var(--color-positive) / <alpha-value>)",
          subtle: "rgb(var(--color-positive-subtle) / <alpha-value>)",
        },
        negative: {
          DEFAULT: "rgb(var(--color-negative) / <alpha-value>)",
          subtle: "rgb(var(--color-negative-subtle) / <alpha-value>)",
        },
        warning: {
          DEFAULT: "rgb(var(--color-warning) / <alpha-value>)",
          subtle: "rgb(var(--color-warning-subtle) / <alpha-value>)",
        },
        sidebar: {
          bg: "rgb(var(--color-sidebar-bg) / <alpha-value>)",
          hover: "rgb(var(--color-sidebar-hover) / <alpha-value>)",
          text: "rgb(var(--color-sidebar-text) / <alpha-value>)",
          "text-muted": "rgb(var(--color-sidebar-text-muted) / <alpha-value>)",
          "active-text": "rgb(var(--color-sidebar-active-text) / <alpha-value>)",
          border: "rgb(var(--color-sidebar-border) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "ui-sans-serif", "sans-serif"],
      },
      boxShadow: {
        sm: "0 1px 2px 0 rgb(15 23 42 / 0.04)",
        md: "0 4px 12px -2px rgb(15 23 42 / 0.08), 0 2px 4px -2px rgb(15 23 42 / 0.04)",
      },
      borderRadius: {
        md: "0.5rem",
        lg: "0.75rem",
        xl: "1rem",
      },
    },
  },
  plugins: [],
};
