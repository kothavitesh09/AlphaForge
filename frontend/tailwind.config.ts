import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./hooks/**/*.{ts,tsx}", "./services/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0B1220",
        panel: "#111827",
        cardHover: "#172033",
        secondary: "#0F172A",
        line: "#1F2937",
        primary: "#3B82F6",
        buy: "#10B981",
        sell: "#EF4444",
        hold: "#F59E0B",
        muted: "#94A3B8"
      },
      boxShadow: {
        card: "0 18px 60px rgba(0,0,0,.22)"
      }
    }
  },
  plugins: []
};

export default config;
