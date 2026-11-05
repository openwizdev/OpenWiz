// #2201: setup's CloudRoom step, its one sign-in screen and the powered-by
// line (contracts/public-cloudroom-setup.v1.md). Display only: the state,
// reason and next step come from GET /api/v1/setup's `cloudroom` component.
import type { SetupComponent } from '../api.ts';

/** The contract's exact wording; shown on the CloudRoom step only. */
export const POWERED_BY = 'Powered by CloudRoom';

export function CloudRoomSetup({ component }: { component: SetupComponent }) {
  const signedIn = component.state === 'verified';
  return <div data-cloudroom-setup={component.state}>
    <h3>CloudRoom sign-in</h3>
    {signedIn
      ? <p>CloudRoom reports you are signed in. Nothing more to do here.</p>
      : <p>You sign in once, in CloudRoom&apos;s own window. OpenWiz never asks for, sees or stores your CloudRoom password or token.</p>}
    <p>Setup installs CloudRoom only when you ask, and reuses an installation and login you already have.</p>
    <p className="meta" data-cloudroom-powered-by="">{POWERED_BY}</p>
  </div>;
}
