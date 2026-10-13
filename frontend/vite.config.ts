import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  build: {
    // `vite build --mode bundle` writes the UI into the Python package (ships in the wheel).
    outDir: mode === 'bundle' ? '../backend/app/static' : 'dist',
    emptyOutDir: true,
    // Transpile for all current evergreen browsers (Chrome, Edge, Firefox, Safari 14+).
    target: ['es2020', 'chrome90', 'edge90', 'firefox90', 'safari14'],
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
}));
