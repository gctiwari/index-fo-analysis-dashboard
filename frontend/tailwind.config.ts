import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: {
          deep: "#0A0E16",
          panel: "#111826",
          alt: "#161F30",
          border: "#232D40",
        },
        ink: {
          DEFAULT: "#E8ECF6",
          muted: "#8A93A8",
          faint: "#5B6478",
        },
        signal: {
          bull: "#33C77E",
          bullDim: "#1D6B47",
          bear: "#F1555C",
          bearDim: "#7A2E33",
          neutral: "#8A93A8",
        },
        gold: {
          DEFAULT: "#E3A53D",
          soft: "#F0C77E",
          dim: "#4A3A1C",
        },
        indigo: {
          DEFAULT: "#6D82F2",
        },
      },
      fontFamily: {
        display: ["var(--font-space-grotesk)", "sans-serif"],
        body: ["var(--font-inter)", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.6)",
      },
    },
  },
  plugins: [],
};
export default config;
