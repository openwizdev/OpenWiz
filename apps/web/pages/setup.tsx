import { useEffect, useState } from 'react';
import { browserFetch, readSetup } from '../src/api.ts';
import type { SetupView } from '../src/api.ts';
import { Button, SoftPanel } from '../src/components/Ui.tsx';
import { SetupComponents, SetupEffects, SetupNext } from '../src/components/Setup.tsx';

export default function SetupPage() {
  const [view, setView] = useState<SetupView | null>(null);
  const [reading, setReading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setReading(true);
    setError(null);
    const timeout = setTimeout(() => controller.abort('timeout'), 10_000);
    void readSetup(browserFetch, controller.signal).then((answer) => {
      if (controller.signal.aborted && controller.signal.reason === 'stop') return;
      if (answer !== 'stopped' && answer.kind === 'ok') setView(answer.envelope);
      else setError(answer !== 'stopped' && answer.kind === 'signed-out'
        ? 'Your access session has expired. Sign in again, then refresh setup.'
        : 'Setup could not be read. Check the local server, then refresh. Connection readiness remains unverified.');
      setReading(false);
      clearTimeout(timeout);
    });
    return () => { clearTimeout(timeout); controller.abort('stop'); };
  }, [revision]);
  return <div className="setup-page">
    <header className="setup-masthead"><span className="wordmark">OpenWiz</span></header>
    <main className="setup-main" data-setup-ready={view !== null && !reading && !error ? 'true' : 'false'}>
      <div className="setup-heading"><h1>Set up OpenWiz</h1><p>Installed. Connect your tools before starting a fleet.</p></div>
      <div className="setup-columns">
        <SoftPanel className="setup-prerequisites" aria-label="Independent prerequisites">
          {view ? <SetupComponents view={view} /> : <p className="setup-initial">Reading independent prerequisites…</p>}
        </SoftPanel>
        <aside className="setup-guidance" aria-label="Next step and engine">
          <SetupNext view={view} />
          <SoftPanel className="setup-engine"><h2>Engine</h2><p>{!view || view.engine === 'unselected' ? 'Not selected' : view.engine === 'cloud' ? 'Cloud' : 'Local'}</p><p>{view?.cost.reason ?? 'Cloud Credits have not been measured.'}</p>
            {view && view.cost.provenance !== 'unknown' && <p>{view.cost.provenance === 'measured' ? 'Measured' : 'Estimated'} Cloud Credits: {view.cost.credits ?? 'unknown'}. Monthly projection: {view.cost.monthly_projection ?? 'unknown'}.</p>}
          </SoftPanel>
          {view && <SetupEffects view={view} />}
        </aside>
      </div>
      <SoftPanel className="setup-footer"><div role="status" aria-live="polite" aria-atomic="true"><p>{error ?? (reading ? 'Reading setup…' : view?.operations.length ? 'Effects are reported above. Readiness is verified independently.' : 'No engine or agents have been started.')}</p>{error && view && <p>Showing the last setup report.</p>}</div><Button disabled={reading} onClick={() => setRevision((value) => value + 1)}>Refresh</Button></SoftPanel>
    </main>
  </div>;
}
