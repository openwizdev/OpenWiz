import type { AppProps } from 'next/app';
import Head from 'next/head';
import '../styles/globals.css';
import '../styles/setup.css';
import '../styles/cockpit.css';
import '../styles/plan.css';
import '../styles/decisions.css';
import '../styles/loops.css';
import '../styles/notifications.css';
import '../styles/feedback.css';
import '../styles/first-hour.css';

export default function OpenWizApp({ Component, pageProps }: AppProps) {
  return (
    <>
      <Head>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <title>OpenWiz</title>
      </Head>
      <Component {...pageProps} />
    </>
  );
}
