// Build yapılandırması.
//
// Emergent şablonundan iki şey ÇIKARILDI:
//   * `@emergentbase/visual-edits` — Emergent'in kendi düzenleyicisine
//     bağlanan bir babel eklentisi; bu depoda karşılığı yok.
//   * `plugins/health-check` — Emergent'in kendi dağıtım denetimi.
//     Sağlık ucumuz zaten backend'de (`/api/v1/health`).
//
// Eklenen tek şey geliştirme proxy'si: `npm start` 3000'de çalışırken
// `/api` istekleri backend'e iletilir. Böylece frontend ile backend
// tarayıcı açısından AYNI origin'de görünür ve CORS'a hiç gerek kalmaz —
// dağıtımda da backend derlenmiş kabuğu kendisi sunduğu için aynı durum
// geçerli olur. İki ortamın aynı şekilde davranması, "geliştirmede
// çalışıyordu" sınıfı hataları baştan siler.
const path = require("path");

const BACKEND_ORIGIN = process.env.JARVIS_BACKEND_ORIGIN || "http://127.0.0.1:8000";

module.exports = {
  eslint: {
    configure: {
      extends: ["plugin:react-hooks/recommended"],
      rules: {
        "react-hooks/rules-of-hooks": "error",
        "react-hooks/exhaustive-deps": "warn",
      },
    },
  },
  webpack: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
    configure: (webpackConfig) => {
      webpackConfig.watchOptions = {
        ...webpackConfig.watchOptions,
        ignored: ["**/node_modules/**", "**/.git/**", "**/build/**", "**/dist/**"],
      };
      return webpackConfig;
    },
  },
  devServer: (devServerConfig) => ({
    ...devServerConfig,
    proxy: [
      {
        context: ["/api"],
        target: BACKEND_ORIGIN,
        changeOrigin: false,
      },
    ],
  }),
};
