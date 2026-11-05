// Synthetic plant at the HTTP boundary: a larger initial load and optional
// 1000-byte growth on every refresh. Each child gets its own result directory.
import { registerHooks } from 'node:module';

registerHooks({
  load(url, context, nextLoad) {
    if (url.endsWith('/test/support/paths.mjs')) {
      return { format: 'module', shortCircuit: true, source: `
        export * from ${JSON.stringify(`${url}?original`)};
        export const RESULTS_DIR = process.env.V11_PROOF_DIR;
      ` };
    }
    if (url.endsWith('/test/support/serve.mjs')) {
      return { format: 'module', shortCircuit: true, source: `
        import assert from 'node:assert/strict';
        import { writeFileSync } from 'node:fs';
        import { startSite as original } from ${JSON.stringify(`${url}?original`)};
        let sites = 0;
        export async function startSite(api) {
          const id = sites++;
          const bytes = [];
          const site = await original((req, res, url) => {
            if (url.pathname === '/api/v1/inventory') {
              const padding = bytes.length === 0 ? 2000 : Number(process.env.V11_PROOF_PADDING);
              let declared;
              const writeHead = res.writeHead.bind(res);
              res.writeHead = (status, headers) => {
                declared = Number(headers['Content-Length']) + padding;
                return writeHead(status, { ...headers, 'Content-Length': String(declared) });
              };
              const end = res.end.bind(res);
              res.end = (body) => {
                const padded = body + ' '.repeat(padding);
                assert.equal(Buffer.byteLength(padded), declared);
                bytes.push(Buffer.byteLength(padded));
                return end(padded);
              };
            }
            return api(req, res, url);
          });
          return { ...site, close: async () => {
            await site.close();
            writeFileSync(process.env.V11_PROOF_DIR + '/answers-' + id + '.json', JSON.stringify(bytes));
          } };
        }
      ` };
    }
    return nextLoad(url, context);
  },
});
