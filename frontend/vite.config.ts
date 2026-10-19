import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发端口 5173；不配置 API 代理，前端直连后端 127.0.0.1:8720。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    strictPort: false
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true
  }
})