/* Free Signature Generator — service worker disabled for ad compatibility.
 * Unregisters any previously installed Sign PDF worker and does not cache fetches.
 * SPDX-License-Identifier: Apache-2.0
 */
self.addEventListener("install", function (event) {
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (key) { return caches.delete(key); }));
    }).then(function () {
      return self.registration.unregister();
    })
  );
});