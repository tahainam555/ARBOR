import { defineConfig } from "@lovable.dev/vite-tanstack-config";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  vite: {
    root: "frontend",
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./frontend/src", import.meta.url)),
      },
    },
  },
});
