import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// What the built page may load. The app ships as file:// pages, so file: is
// listed next to 'self'. Preset artwork is a data: URL, and SFX clips play from
// file: paths and bundled assets. No remote origin is allowed anywhere.
const CSP = [
  "default-src 'self' file:",
  "script-src 'self' file:",
  "style-src 'self' file:",
  "img-src 'self' file: data: blob:",
  "media-src 'self' file: data: blob:",
  "font-src 'self' file: data:",
  "connect-src 'self' file:",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-src 'none'",
].join("; ");

// Added at build time only: the dev server injects inline scripts for hot
// reload, which this policy would block.
function contentSecurityPolicy(): Plugin {
  return {
    name: "overtone-csp",
    apply: "build",
    transformIndexHtml: () => [{ tag: "meta", attrs: { "http-equiv": "Content-Security-Policy", content: CSP }, injectTo: "head-prepend" }],
  };
}

export default defineConfig({
  plugins: [react(), contentSecurityPolicy()],
  base: "./",
  css: {
    modules: {
      // Stable, readable class names in devtools and in diffs. Without this the
      // default hash changes whenever any file's content changes, which makes
      // CSS-only commits noisy.
      generateScopedName: "[name]__[local]___[hash:base64:5]",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
    fs: {
      // desktop/shared/opts-spec.json lives above the Vite root.
      allow: [".."],
    },
  },
});
