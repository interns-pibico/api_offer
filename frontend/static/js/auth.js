/* api_offer — auth.js v1
   Global auth state: checks token, updates header user menu.
*/
(function () {
  'use strict';

  const ROOT = window.OFFER_ROOT || '';

  const guestEl   = document.getElementById('user-guest');
  const loggedEl   = document.getElementById('user-logged');
  const avatarBtn  = document.getElementById('user-avatar-btn');
  const initialEl  = document.getElementById('user-initial');
  const dropdown   = document.getElementById('user-dropdown');
  const nameEl     = document.getElementById('user-dropdown-name');
  const logoutBtn  = document.getElementById('btn-logout');

  if (!guestEl) return;

  // Expose global auth state
  window.offerAuth = {
    token: null,
    user: null,
    isLoggedIn: false,
    onReady: [],  // callbacks fired when auth check completes
  };

  // Mobile drawer auth link
  var mobileLogin = document.getElementById('mobile-drawer-login');

  function showLoggedIn(user) {
    window.offerAuth.user = user;
    window.offerAuth.isLoggedIn = true;
    guestEl.style.display = 'none';
    loggedEl.style.display = '';
    initialEl.textContent = (user.username || 'U')[0].toUpperCase();
    nameEl.textContent = user.username;
    if (mobileLogin) mobileLogin.style.display = 'none';
  }

  function showGuest() {
    window.offerAuth.user = null;
    window.offerAuth.isLoggedIn = false;
    guestEl.style.display = '';
    loggedEl.style.display = 'none';
    if (mobileLogin) mobileLogin.style.display = '';
  }

  async function checkAuth() {
    var token = localStorage.getItem('offer_token');
    if (!token) {
      showGuest();
      fireReady();
      return;
    }
    window.offerAuth.token = token;
    try {
      var resp = await fetch(ROOT + '/api/v1/auth/me', {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (resp.ok) {
        var user = await resp.json();
        showLoggedIn(user);
      } else {
        localStorage.removeItem('offer_token');
        window.offerAuth.token = null;
        showGuest();
      }
    } catch (e) {
      showGuest();
    }
    fireReady();
  }

  function fireReady() {
    for (var cb of window.offerAuth.onReady) {
      try { cb(); } catch (e) { console.error(e); }
    }
  }

  // Dropdown toggle
  if (avatarBtn) {
    avatarBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      dropdown.style.display = dropdown.style.display === 'none' ? '' : 'none';
    });
  }

  // Close dropdown on outside click
  document.addEventListener('click', function () {
    if (dropdown) dropdown.style.display = 'none';
  });

  // Logout
  if (logoutBtn) {
    logoutBtn.addEventListener('click', function () {
      localStorage.removeItem('offer_token');
      window.offerAuth.token = null;
      window.offerAuth.user = null;
      window.offerAuth.isLoggedIn = false;
      showGuest();
      if (dropdown) dropdown.style.display = 'none';
    });
  }

  checkAuth();
})();
