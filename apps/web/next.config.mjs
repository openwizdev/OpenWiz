// A static export (`out/`), served same-origin under `/` by openwiz-server
// (option (a)). The app calls `/api/v1/...` with relative URLs only.
import { rmSync, writeFileSync } from 'node:fs';

// RL4 (#1148): a packaging build's export carries the product identity it is
// built for, generated now (public/ is copied into this export), never added
// to an old export. Every other build, the service's update included, carries
// none. contracts/release-candidate.v1.md, "Minimum product identity (RL4)".
const productIdentity = new URL('./public/openwiz-product.json', import.meta.url);
const { OPENWIZ_BUILD_VERSION: version, OPENWIZ_BUILD_TARGET: target, OPENWIZ_SERVICE_BUILD: source } = process.env;
rmSync(productIdentity, { force: true });
if (version !== undefined || target !== undefined) {
  const targets = ['aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-unknown-linux-gnu'];
  if (!/^0\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.test(version ?? '') || !targets.includes(target) || !/^[0-9a-f]{40}$/.test(source ?? '')) {
    throw new Error('openwiz: incomplete or malformed web build identity');
  }
  writeFileSync(productIdentity, `${JSON.stringify({ product: 'web', schema: 'openwiz.product.v1', source, target, version })}\n`);
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  images: { unoptimized: true },
  trailingSlash: false,
  poweredByHeader: false,
  reactStrictMode: true,
  productionBrowserSourceMaps: false,
  webpack(config) {
    // webpack's `global` runtime falls back to Function("return this")() when
    // globalThis is missing; a CSP without 'unsafe-eval' refuses that, and every
    // browser we support has globalThis. So the runtime is just globalThis
    // (Sol 5). Next's bundled webpack ignores output.environment.globalThis here.
    config.plugins.push({
      apply(compiler) {
        compiler.hooks.compilation.tap('OpenWizGlobalThis', (compilation) => {
          compilation.hooks.runtimeModule.tap('OpenWizGlobalThis', (module) => {
            if (module.name === 'global') module.generate = () => '__webpack_require__.g = globalThis;';
          });
        });
      },
    });
    return config;
  },
};

export default nextConfig;
