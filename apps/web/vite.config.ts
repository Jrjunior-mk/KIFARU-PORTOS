import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

// Dev proxy: /api and /ws go to the FastAPI backend. In production VITE_API_BASE points at the API origin
// (or stays empty when nginx proxies /api on the same origin — see Dockerfile / nginx.conf.template).
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'icons/icon.svg', 'icons/icon-maskable.svg'],
      manifest: {
        name: 'KIFARU PORTOS',
        short_name: 'KIFARU',
        description: 'Kenya Intelligent Freight, Access, Routing & Unified Logistics Platform',
        theme_color: '#0f172a',
        background_color: '#0f172a',
        display: 'standalone',
        start_url: '/',
        scope: '/',
        icons: [
          { src: '/icons/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
          { src: '/icons/icon-maskable.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'maskable' },
        ],
        shortcuts: [
          { name: 'Cargo owner', url: '/owner', description: 'Shipment passport and alerts' },
          { name: 'Driver screen', url: '/driver', description: 'Clearance and queue status' },
        ],
      },
      workbox: {
        // Cache the app shell only; API responses are never cached so simulated/live data is always fresh.
        globPatterns: ['**/*.{js,css,html,svg,woff2}'],
        // Keep the precached shell small for low-bandwidth users: the map, 3D and chart chunks are fetched on demand
        // and then cached at runtime (see runtimeCaching below).
        globIgnores: ['**/assets/map-*.js', '**/assets/three-*.js', '**/assets/charts-*.js', '**/assets/StationMap-*.{js,css}', '**/assets/Twin-*.js'],
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/ws\//, /^\/docs/, /^\/openapi\.json/],
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
        runtimeCaching: [
          {
            urlPattern: ({ url, sameOrigin }) => sameOrigin && url.pathname.startsWith('/assets/'),
            handler: 'StaleWhileRevalidate',
            options: { cacheName: 'app-assets', expiration: { maxEntries: 60, maxAgeSeconds: 30 * 24 * 3600 } },
          },
          {
            urlPattern: /^https:\/\/tile\.openstreetmap\.org\/.*/i,
            handler: 'CacheFirst',
            options: { cacheName: 'osm-tiles', expiration: { maxEntries: 200, maxAgeSeconds: 7 * 24 * 3600 } },
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true, changeOrigin: true },
    },
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          charts: ['recharts'],
          map: ['maplibre-gl'],
          three: ['three', '@react-three/fiber', '@react-three/drei'],
        },
      },
    },
  },
});
