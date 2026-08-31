import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import {
  appFeatureChunk,
  normalizeModuleId,
  type ChunkName,
} from './src/app/chunk-config.ts';

function vendorChunk(id: string): ChunkName {
  const normalizedId = normalizeModuleId(id);

  if (!normalizedId.includes('node_modules')) {
    return undefined;
  }
  if (
    normalizedId.includes('/react/') ||
    normalizedId.includes('/react-dom/')
  ) {
    return 'react-vendor';
  }
  if (normalizedId.includes('/@tanstack/')) {
    return 'tanstack';
  }
  if (normalizedId.includes('/recharts/') || normalizedId.includes('/d3-')) {
    return 'charts';
  }
  if (normalizedId.includes('/react-hook-form/')) {
    return 'forms';
  }
  if (normalizedId.includes('/lucide-react/')) {
    return 'icons';
  }

  return undefined;
}

export default defineConfig({
  plugins: [tailwindcss(), react()],
  build: {
    rollupOptions: {
      output: {
        codeSplitting: {
          includeDependenciesRecursively: false,
          groups: [
            {
              name: (id) => appFeatureChunk(id) ?? null,
              priority: 2,
            },
            {
              name: (id) => vendorChunk(id) ?? null,
              priority: 1,
            },
          ],
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: process.env.KARKINOS_DEV_BACKEND_URL ?? 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
      '/ws': {
        target: (
          process.env.KARKINOS_DEV_BACKEND_URL ?? 'http://127.0.0.1:8001'
        ).replace(/^http/, 'ws'),
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
