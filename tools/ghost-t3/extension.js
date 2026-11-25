"use strict";

/* Runs before sidecar.js in the extension's isolated world and names the session.
   Engine calls stay in background.js. The desktop injector does not use this file. */
globalThis.__openwizGhostSession = "ses-syn-ext";
