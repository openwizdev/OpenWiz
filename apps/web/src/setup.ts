// Setup page wording and status marks (#1105). Pure: no fetch, no effects.
// T4 (`engine`, `activate_engine`) and T5 (`remote_access`, `configure_access`)
// change only their own lines here.
import type { SetupComponent, SetupComponentId, SetupView } from './api.ts';

export function componentName(id: SetupComponentId): string {
  switch (id) {
    case 'cloudroom': return 'CloudRoom';
    case 'harness': return 'Agent harness';
    case 'personal_github': return 'Personal GitHub';
    case 'github_app': return 'OpenWiz GitHub App';
    case 'project': return 'Project';
    case 'engine': return 'Engine';
    case 'remote_access': return 'Phone access';
  }
}

/** Refused and missing need the owner; verified is settled; unknown is unproven. */
export function componentTier(state: SetupComponent['state']): 't1' | 't2' | 't5' {
  return state === 'missing' || state === 'refused' ? 't1' : state === 'verified' ? 't2' : 't5';
}

export function operationName(kind: SetupView['operations'][number]['kind']): string {
  switch (kind) {
    case 'connect_app': return 'Connect OpenWiz GitHub App';
    case 'prepare_project': return 'Prepare project';
    case 'activate_engine': return 'Activate engine';
    case 'configure_access': return 'Configure phone access';
  }
}

/** The first component that needs the owner, in setup order, or null. */
export function nextComponent(view: SetupView): SetupComponent | null {
  return view.components.find((c) => c.id !== 'engine' && c.id !== 'remote_access' && c.state !== 'verified') ?? null;
}
