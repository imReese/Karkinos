import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

type ChunkName = string | undefined;

function normalizeModuleId(id: string) {
  return id.replace(/\\/g, '/');
}

function appFeatureChunk(id: string): ChunkName {
  const normalizedId = normalizeModuleId(id);

  if (!normalizedId.includes('/src/features/')) {
    return undefined;
  }

  if (normalizedId.includes('/src/features/account-strategy/')) {
    return 'feature-account-strategy';
  }
  if (normalizedId.includes('/src/features/account-truth/')) {
    return 'feature-account-truth';
  }
  if (
    normalizedId.includes('/src/features/account/') ||
    normalizedId.includes('/src/features/market/')
  ) {
    return 'feature-account-market';
  }
  if (normalizedId.includes('/src/features/activity/')) {
    return 'feature-activity';
  }
  if (normalizedId.includes('/src/features/backtest/')) {
    return 'feature-backtest';
  }
  if (normalizedId.includes('/src/features/decision/')) {
    return 'feature-decision';
  }
  if (normalizedId.includes('/src/features/portfolio/')) {
    return 'feature-portfolio';
  }
  if (normalizedId.includes('/src/features/settings/')) {
    return 'feature-settings';
  }
  if (normalizedId.includes('/src/features/trading/')) {
    return 'feature-trading';
  }

  return undefined;
}

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
  plugins: [react()],
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
