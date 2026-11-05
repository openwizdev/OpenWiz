// OpenWiz's one service worker registration (#1029): the app shell's worker,
// /sw.js, for the whole app. It touches nothing else; if registering fails,
// the app works as before, from the network.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
  });
}
