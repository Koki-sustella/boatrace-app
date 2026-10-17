import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// Deployed at https://koki-sustella.github.io/boatrace-app/ (GitHub Pages project site)
const BASE = "/boatrace-app/";

export default defineConfig({
  base: BASE,
  build: {
    // site/data/*.parquet is produced separately by scripts/export_parquet.py
    // (in the same CI run) -- never let a frontend build wipe it out.
    outDir: "../site",
    emptyOutDir: false,
  },
  plugins: [
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icons/*.png"],
      manifest: {
        name: "ボートレース選手成績データ",
        short_name: "競艇成績",
        description: "ボートレース全選手の成績を場×コース×グレードで横断検索する個人用アプリ",
        start_url: BASE,
        scope: BASE,
        display: "standalone",
        background_color: "#0b1220",
        theme_color: "#0b1220",
        icons: [
          { src: "icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icons/icon-512-maskable.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        // Activate a newly-installed service worker immediately instead of the
        // browser's default "wait until every open tab/PWA instance of the old
        // version is closed" behavior. Without this, a user who keeps the PWA
        // open (or revisits via a home-screen icon, which doesn't do a normal
        // reload) can be stuck on a stale cached build indefinitely even after
        // a new version is deployed and even after they manually reload.
        skipWaiting: true,
        clientsClaim: true,
        // App shell: precache + cache-first via workbox default (handled by globPatterns).
        // DuckDB-WASM's .wasm binaries (~35-40MB each, mvp vs eh picked at runtime
        // depending on browser support -- only one is ever actually used) are
        // deliberately excluded from eager precaching and cached on first real use
        // instead (see runtimeCaching below), so install doesn't force a ~70MB
        // download of both variants up front.
        globPatterns: ["**/*.{js,css,html,svg,png,ico}"],
        runtimeCaching: [
          {
            // Data files are large (MB-scale) and refreshed daily by CI: serve the
            // cached copy instantly, then refresh it in the background for next time.
            urlPattern: /\/data\/.*\.parquet$/,
            handler: "StaleWhileRevalidate",
            options: {
              cacheName: "boatrace-data",
              cacheableResponse: { statuses: [0, 200] },
              expiration: { maxEntries: 32, maxAgeSeconds: 60 * 60 * 24 * 14 },
            },
          },
          {
            // DuckDB-WASM engine binary: content-hashed filename, so once cached
            // it never needs re-validating until the app itself is rebuilt.
            urlPattern: /\.wasm$/,
            handler: "CacheFirst",
            options: {
              cacheName: "boatrace-wasm",
              cacheableResponse: { statuses: [0, 200] },
              expiration: { maxEntries: 4, maxAgeSeconds: 60 * 60 * 24 * 180 },
            },
          },
        ],
      },
    }),
  ],
});
