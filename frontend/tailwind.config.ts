import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        app: {
          bg: "var(--bg-primary)",
          surface: "var(--bg-surface)",
          active: "var(--bg-active)",
          menu: "var(--bg-menu-active)",
          hover: "var(--bg-hover)",
          border: "var(--border)",
          strong: "var(--border-strong)",
          text: "var(--text-primary)",
          muted: "var(--text-muted)",
          white: "var(--text-active)",
          primary: "var(--primary)",
          secondary: "var(--primary-soft)",
          success: "var(--success)",
          infoBg: "var(--bg-info)",
          successBg: "var(--bg-success)"
        }
      },
      borderRadius: {
        control: "var(--radius-control)",
        card: "var(--radius-card)",
        pill: "var(--radius-pill)"
      },
      fontFamily: {
        sans: ["Plus Jakarta Sans", "system-ui", "sans-serif"]
      },
      boxShadow: {
        soft: "0 16px 40px rgba(0, 0, 0, 0.24)"
      }
    }
  },
  plugins: []
} satisfies Config;
