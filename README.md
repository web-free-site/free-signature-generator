# Free Signature Generator

https://free-signature-generator.web-free.site

Draw or type a signature, download a transparent PNG, and sign PDF files locally in the browser. Based on [TekiDeki/Sign-PDF](https://github.com/TekiDeki/Sign-PDF) (Apache-2.0).

## Build

```bash
python3 build.py
```

Produces `index.html` and a Cloudflare-ready `dist/` directory (static assets only).

## Tests

```bash
npm install pdf-lib@1.17.1
node tests/logic_test.cjs
```

Optional UI tests (Playwright):

```bash
python3 tests/ui_test.py
```

## Deploy

`wrangler.toml` points `[assets]` at `dist/`. Deployment is handled outside this repo.