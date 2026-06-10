/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/templates/**/*.html"],
  theme: {
    extend: {
      colors: { brand: { DEFAULT: "#10b981", dark: "#059669" } },
    },
  },
  // Classes montadas dinamicamente nos flashes (bg-{cor}-500/10 etc.) não são
  // detectadas pelo scanner — precisam ser preservadas explicitamente.
  safelist: [
    "bg-emerald-500/10", "bg-red-500/10", "bg-amber-500/10", "bg-sky-500/10", "bg-slate-500/10",
    "border-emerald-500/30", "border-red-500/30", "border-amber-500/30", "border-sky-500/30", "border-slate-500/30",
    "text-emerald-300", "text-red-300", "text-amber-300", "text-sky-300", "text-slate-300",
  ],
};
