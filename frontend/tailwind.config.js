/** @type {import('tailwindcss').Config} */
let defaultConfig = {};

// Try known safe entry points from the shadcn package; if they don't exist,
// fall back to a minimal default so Tailwind can run.
try {
  // preferred: named export path used by older shadcn setups
  defaultConfig = require("shadcn/ui/tailwind.config");
} catch (e1) {
  try {
    // try to require from dist if available
    defaultConfig = require("shadcn/dist/tailwind.config.cjs");
  } catch (e2) {
    // fallback minimal config
    defaultConfig = {
      theme: { extend: {} },
      plugins: [],
    };
  }
}

module.exports = {
  ...defaultConfig,
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}", "*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    ...defaultConfig.theme,
    extend: {
      ...(defaultConfig.theme && defaultConfig.theme.extend ? defaultConfig.theme.extend : {}),
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [...(defaultConfig.plugins || []), require("tailwindcss-animate")],
};
