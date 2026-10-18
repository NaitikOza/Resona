import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17323a",
        mist: "#edf4f2",
        teal: {
          50: "#effcf9",
          100: "#d8f5ee",
          200: "#b2eadc",
          300: "#7bd8c7",
          400: "#43bfac",
          500: "#269f8e",
          600: "#1b8075",
          700: "#19675f",
          800: "#18534e",
          900: "#174642"
        },
        coral: "#ea7b5d",
        amber: "#d69a36"
      },
      boxShadow: {
        soft: "0 24px 70px -38px rgba(23, 50, 58, 0.45)",
        panel: "0 12px 36px -22px rgba(23, 50, 58, 0.35)"
      },
      fontFamily: {
        sans: ["Inter", "Avenir Next", "Segoe UI", "sans-serif"],
        display: ["Iowan Old Style", "Palatino Linotype", "serif"]
      }
    },
  },
  plugins: [],
};

export default config;

