// The setup page's independent components and recorded effects (#1105).
// Display only: every state comes from GET /api/v1/setup.
import { useState } from 'react';
import type { SetupView } from '../api.ts';
import { componentName, componentTier, nextComponent, operationName } from '../setup.ts';
import { CloudRoomSetup } from './CloudRoomSetup.tsx';
import { StatusGlyph } from './StatusMark.tsx';
import { SoftPanel } from './Ui.tsx';

export function SetupComponents({ view }: { view: SetupView }) {
  return <>{view.components.map((component) => <section key={component.id} data-setup-component={component.id}>
    <details><summary className="setup-component-head" aria-label={`${componentName(component.id)}: ${component.state}. Read reason and next step`}><StatusGlyph tier={componentTier(component.state)} /><span className="setup-component-name">{componentName(component.id)}</span><span className="setup-state">{component.state}</span></summary><p>{component.reason}</p><p>{component.next}</p>{component.id === 'cloudroom' && <CloudRoomSetup component={component} />}{component.id === 'remote_access' && <SetupAccess />}</details>
  </section>)}</>;
}

/** T5: guidance only. Choosing a route never authorizes or activates it. */
function SetupAccess() {
  const [route, setRoute] = useState('cloudflare');
  return <div data-setup-access={route}>
    <p>Choose an authenticated route. A running tunnel alone is not ready.</p>
    <label htmlFor="setup-access-route" className="pick-label">Phone access route</label>
    <select id="setup-access-route" className="pick-select btn" value={route} onChange={(event) => setRoute(event.target.value)}>
      <option value="cloudflare">Cloudflare Tunnel + Access</option>
      <option value="tailscale">Tailscale</option>
    </select>
    <h3>Before you begin</h3>
    {route === 'cloudflare'
      ? <><p>Cloudflare account, managed domain, Zero Trust and cloudflared on the engine host.</p><p>No account or domain? Choose Tailscale or review those prerequisites first. No hidden purchase.</p></>
      : <><p>Tailscale account, Tailscale on your phone and engine host, and permission to set owner-only access rules and enable HTTPS.</p><p>A managed domain is not required. Review current account limits and any cost before agreeing. No hidden purchase.</p></>}
    <h3>Set up with your installing agent</h3>
    <ol>
      <li>Review effects and approve the exact setup operation before making account or network changes.</li>
      {route === 'cloudflare'
        ? <><li>Create a named tunnel and an owner-only Access policy for all paths. No Bypass or Service Auth policy.</li><li>Route only the HTTPS hostname to loopback and require Access at the origin, with the correct team and application audience. Cloudflare handles traffic at its edge. No quick tunnel.</li></>
        : <><li>Use private Tailscale Serve with HTTPS to the loopback server. Keep Funnel off.</li><li>Restrict access rules to your owner identity and selected engine host. Tailscale&apos;s default allow-all policy does not establish owner-only access.</li></>}
      <li>Keep the server&apos;s allowed HTTPS host, same-origin, request and once-only write checks.</li>
      <li>Verify owner access and refusal for unauthenticated, expired and foreign sessions before reporting phone access ready. Denied requests must never reach a write.</li>
    </ol>
    <h3>Recovery</h3><p>Sign in again after expired or denied access. Keep your draft and operation ID. After network loss or host restart, restore the same authenticated route and check status before retrying uncertain work. Reconnecting never resends work.</p><p>Refresh reads the latest setup report. Choosing these instructions grants no authority and starts no tunnel.</p>
  </div>;
}

/** #1109, reconciled by #2293 (contracts/public-offer.v1.md): CloudRoom's own
 * pricing page, shown as text: the app makes no outbound links. OpenWiz is free
 * now and paid plans come later; a CloudRoom purchase is upstream and separate,
 * never an OpenWiz upgrade. No owner-supplied referral is verified, so none is
 * applied and the panel says so: add one only through a reviewed change to this
 * constant and the site's link. */
export const CLOUDROOM_UPGRADE = 'cloudroom.dev/pricing';

export function SetupCost() {
  return <SoftPanel className="setup-cost" data-setup-cost="cloudroom"><h2>Cost</h2>
    <p>OpenWiz is free now. Paid plans come later. CloudRoom and model charges are separate and not included.</p>
    <p>CloudRoom sells its own plans at <span className="word">{CLOUDROOM_UPGRADE}</span>. Referral verification is unavailable. No referral is applied.</p>
  </SoftPanel>;
}

export function SetupNext({ view }: { view: SetupView | null }) {
  const next = view ? nextComponent(view) : null;
  return <><SoftPanel className="setup-next" data-setup-next={next?.id ?? 'none'}>
    {!view || (next && next.id === 'cloudroom' && next.state === 'unknown' && view.operations.length === 0
      && !view.components.some((c) => c.state === 'verified'))
      ? <><h2>Start with CloudRoom</h2><p>Ask your installing agent to check CloudRoom and your chosen harness.</p></>
      : next ? <><h2>Next: {componentName(next.id)}</h2><p>{next.next}</p></>
        : <><h2>Connections verified</h2><p>Choose where the engine runs next. Nothing starts without your approval.</p></>}
  </SoftPanel><SetupCost /></>;
}

export function SetupEffects({ view }: { view: SetupView }) {
  if (view.operations.length === 0) return null;
  return <SoftPanel className="setup-effects"><h2>Setup effects</h2>{view.operations.map((operation) => <section key={operation.operation_id} data-setup-operation={operation.kind} data-setup-phase={operation.phase}>
    <p>{operationName(operation.kind)}, {operation.phase}: {operation.reason}</p><ul>{operation.effects.map((effect, at) => <li key={at}><span className="word">{effect}</span></li>)}</ul>
  </section>)}</SoftPanel>;
}
