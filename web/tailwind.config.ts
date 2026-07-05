import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // theme-aware semantic tokens (driven by CSS vars in globals.css)
        bg: "var(--nx-bg)",
        fg: "var(--nx-fg)",
        muted: "var(--nx-muted)",
        dim: "var(--nx-dim)",
        surface: "var(--nx-surface)",
        "surface-solid": "var(--nx-surface-solid)",
        line: "var(--nx-line)",
        "line-strong": "var(--nx-line-strong)",
        accent: { DEFAULT: "var(--nx-accent)", strong: "var(--nx-accent-strong)" },

        // Vibrant "Aurora" accent. NOTE: the legacy class names `indigo`, `blue`
        // and `grape` are remapped onto a violet ramp and `pink` onto fuchsia, so
        // existing components reskin without per-file edits.
        violet: { 300: "#c4b5fd", 400: "#a78bfa", 500: "#8b5cf6", 600: "#7c3aed", 700: "#6d28d9" },
        cyan: { 400: "#22d3ee", 500: "#06b6d4", 600: "#0891b2" },
        blue: { 300: "#c4b5fd", 400: "#a78bfa", 500: "#8b5cf6", 600: "#7c3aed", 700: "#6d28d9" },
        indigo: { 300: "#c4b5fd", 400: "#a78bfa", 500: "#8b5cf6", 600: "#7c3aed" },
        pink: { 300: "#f0abfc", 400: "#e879f9", 500: "#d946ef" },
        grape: { 400: "#a78bfa", 500: "#8b5cf6" },
        iris: { DEFAULT: "#ddd6fe" },

        // semantic status colors — vibrant
        mint: { 300: "#6ee7b7", 500: "#10b981" },
        amber: { 400: "#fbbf24", 500: "#f59e0b" },
        rose: { 400: "#fb7185", 500: "#f43f5e" },

        // backward-compatible aliases
        primary: { 50: "#f5f3ff", 100: "#ede9fe", 500: "#8b5cf6", 600: "#7c3aed", 700: "#6d28d9" },
        success: { 500: "#10b981", bg: "rgba(16,185,129,0.14)" },
        danger: { 500: "#f43f5e", bg: "rgba(244,63,94,0.14)" },
        warning: { 500: "#f59e0b", bg: "rgba(245,158,11,0.14)" },
      },
      fontFamily: {
        heading: ["Space Grotesk", "IBM Plex Sans Arabic", "system-ui", "sans-serif"],
        sans: ["IBM Plex Sans", "IBM Plex Sans Arabic", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      borderRadius: { card: "18px" },
      backgroundImage: {
        // aurora: violet -> cyan -> fuchsia (theme-aware via --grad-aurora)
        "grad-brand": "var(--grad-aurora)",
        "grad-iris": "var(--grad-aurora)",
        aurora: "var(--grad-aurora)",
      },
      boxShadow: {
        card: "var(--shadow)",
        lift: "0 18px 44px -20px rgba(124,58,237,0.45)",
        glow: "0 10px 30px -10px var(--glow-violet)",
      },
      keyframes: {
        "pulse-border": {
          "0%, 100%": { borderColor: "rgba(124,58,237,0.28)" },
          "50%": { borderColor: "rgba(124,58,237,0.7)" },
        },
        "fade-up": {
          from: { opacity: "0", transform: "translateY(16px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        floaty: { "0%, 100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-10px)" } },
        blink: { "0%, 100%": { opacity: "1" }, "50%": { opacity: "0.15" } },
        "spin-glow": { to: { transform: "rotate(360deg)" } },
      },
      animation: {
        "pulse-border": "pulse-border 2.6s ease-in-out infinite",
        "fade-up": "fade-up .5s ease-out both",
        floaty: "floaty 6s ease-in-out infinite",
        blink: "blink 1.1s steps(1) infinite",
        "spin-glow": "spin-glow 9s linear infinite",
      },
    },
  },
  plugins: [],
};
export default config;
