import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import { VitePWA } from "vite-plugin-pwa"

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.ts",
      registerType: "autoUpdate",
      injectRegister: false,
      manifest: {
        name: "EverFit",
        short_name: "EverFit",
        description: "Coach nutrizionale personale sopra Cronometer",
        lang: "it",
        start_url: "/",
        display: "standalone",
        background_color: "#0A0C0F",
        theme_color: "#0A0C0F",
        icons: [
          { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      injectManifest: {
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        globIgnores: ["**/inter-{cyrillic,greek,vietnamese}*"],
      },
      devOptions: { enabled: false },
    }),
  ],
  server: { port: 5178, proxy: { "/api": "http://127.0.0.1:8096" } },
})
