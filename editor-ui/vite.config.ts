/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

const repoRoot = fileURLToPath(new URL('..', import.meta.url));
// Where `npm run dev` sends API calls: the mock server by default, or a real
// `manimgl-editor` when EDITOR_API points at it.
const apiTarget = process.env.EDITOR_API ?? 'http://127.0.0.1:8790';

export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: '../manim_verbose/editor/static',
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 800,
  },
  server: {
    port: 5173,
    strictPort: false,
    fs: { allow: [repoRoot] },
    proxy: {
      '/api': { target: apiTarget, changeOrigin: false },
      '/files': { target: apiTarget, changeOrigin: false },
      '/__mock': { target: apiTarget, changeOrigin: false },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    pool: 'threads',
    maxWorkers: 2,
    testTimeout: 20000,
  },
});
