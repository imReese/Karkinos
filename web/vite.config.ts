import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import {
  appFeatureChunk,
  normalizeModuleId,
  type ChunkName,
} from './src/app/chunk-config';

function vendorChunk(id: string): ChunkName {
  const normalizedId = normalizeModuleId(id);

  if (!normalizedId.includes('node_modules')) {
    return undefined;
  }
  if (normalizedId.includes('/react/') || normalizedId.includes('/react-dom/')) {
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
        manualChunks(id) {
          const appChunk = appFeatureChunk(id);

          if (appChunk) {
            return appChunk;
          }

          return vendorChunk(id);
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
