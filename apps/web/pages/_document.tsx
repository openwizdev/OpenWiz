import { Head, Html, Main, NextScript } from 'next/document';

// The fonts are bundled (public/fonts, OFL 1.1). Nothing is loaded from
// another origin. The installable app (#1029): the manifest, the touch icon
// and the one script that registers the app-shell worker, all bundled in
// public/; the worker and its registration stay there, outside the checked
// sources.
export default function Document() {
  return (
    <Html lang="en">
      <Head>
        <meta name="color-scheme" content="dark" />
        <meta name="theme-color" content="#0e0f11" />
        <link rel="manifest" href="/manifest.webmanifest" />
        <link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" />
        <script src="/sw-register.js" defer />
        <link rel="preload" href="/fonts/Geist-var.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
        <link rel="preload" href="/fonts/GeistMono-var.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
      </Head>
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
