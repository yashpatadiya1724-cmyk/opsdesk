import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class", '[data-theme="dark"]'],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Stitch Target Palette ("Paper + Teal + Clay")
        paper: "#F6F3EE",
        surface: {
          DEFAULT: "#FDFCFA",
          subtle: "#F6F3EE",
        },
        line: {
          DEFAULT: "#E4DED5",
          subtle: "#E4DED5",
        },
        ink: {
          DEFAULT: "#1C1B19",
          soft: "#5E5A53",
          mute: "#706B63",
        },
        brand: {
          DEFAULT: "#115E59",
          hover: "#0B4745",
          soft: "#E3EFEE",
        },
        clay: {
          DEFAULT: "#D9733A",
          text: "#9A4A1E",
          soft: "#FBEFE6",
          line: "#EBCDB8",
        },
        sla: {
          ok: {
            bg: "#E6F0E8",
            fg: "#25623A",
            line: "#CFE0D3",
          },
          risk: {
            bg: "#FBF0D0",
            fg: "#7A5200",
            line: "#E8D58A",
          },
          breach: {
            bg: "#F8E1DE",
            fg: "#9B1C1C",
            line: "#EDB9B3",
          },
          stop: {
            bg: "#ECEAE6",
            fg: "#55524C",
            line: "#D6D2CB",
          },
          // Backward-compatibility aliases for existing components/tests
          normal: {
            bg: "#E6F0E8",
            text: "#25623A",
            line: "#CFE0D3",
          },
          at_risk: {
            bg: "#FBF0D0",
            text: "#7A5200",
            line: "#E8D58A",
          },
          breached: {
            bg: "#F8E1DE",
            text: "#9B1C1C",
            line: "#EDB9B3",
          },
          stopped: {
            bg: "#ECEAE6",
            text: "#55524C",
            line: "#D6D2CB",
          },
          escalated: {
            bg: "#EDE9FE",
            text: "#6D28D9",
            line: "#DDD6FE",
          },
        },
        note: {
          bg: "#F1EDF7",
          border: "#D6CCE6",
          lock: "#5B4A86",
        },
        priority: {
          urgent: {
            DEFAULT: "#B42318",
            dot: "#B42318",
            text: "#B42318",
            bg: "#FDFCFA",
            border: "#E4DED5",
          },
          high: {
            DEFAULT: "#D9733A",
            dot: "#D9733A",
            text: "#D9733A",
            bg: "#FDFCFA",
            border: "#E4DED5",
          },
          medium: {
            DEFAULT: "#6B7C93",
            dot: "#6B7C93",
            text: "#6B7C93",
            bg: "#FDFCFA",
            border: "#E4DED5",
          },
          low: {
            DEFAULT: "#A8A196",
            dot: "#A8A196",
            text: "#A8A196",
            bg: "#FDFCFA",
            border: "#E4DED5",
          },
        },
        border: {
          DEFAULT: "#E4DED5",
          strong: "#5E5A53",
        },
        content: {
          primary: "#1C1B19",
          secondary: "#5E5A53",
          tertiary: "#706B63",
          disabled: "#A8A196",
          muted: "#706B63",
        },
        "focus-ring": "#115E59",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "DM Sans", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "Roboto", "sans-serif"],
        heading: ["var(--font-sans)", "DM Sans", "-apple-system", "BlinkMacSystemFont", "sans-serif"],
        mono: ["var(--font-mono)", "IBM Plex Mono", "monospace"],
      },
      fontSize: {
        11: ["11px", { lineHeight: "14px", letterSpacing: "0.04em" }],
        12: ["12px", { lineHeight: "16px" }],
        13: ["13px", { lineHeight: "20px" }],
        14: ["14px", { lineHeight: "20px" }],
        16: ["16px", { lineHeight: "24px" }],
        20: ["20px", { lineHeight: "28px" }],
        28: ["28px", { lineHeight: "36px" }],
        caption: ["12px", { lineHeight: "16px" }],
        table: ["13px", { lineHeight: "20px" }],
        body: ["14px", { lineHeight: "20px" }],
        section: ["16px", { lineHeight: "24px" }],
        page: ["20px", { lineHeight: "28px" }],
        kpi: ["28px", { lineHeight: "36px" }],
        "micro-label": ["11px", { lineHeight: "14px", letterSpacing: "0.04em" }],
      },
      borderRadius: {
        input: "6px",
        chip: "6px",
        card: "8px",
        modal: "8px",
        panel: "8px",
        island: "8px",
        8: "8px",
        6: "6px",
        4: "4px",
      },
      boxShadow: {
        xs: "none",
        sm: "none",
        md: "none",
        lg: "none",
        flat: "none",
      },
      keyframes: {
        "sla-breach-pulse": {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.8", transform: "scale(1.04)" },
        },
      },
      animation: {
        "sla-breach": "sla-breach-pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
    },
  },
  plugins: [],
};

export default config;
