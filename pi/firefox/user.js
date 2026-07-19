// Visio-TV kiosk Firefox profile prefs. Copied to the profile dir by install.sh.

// CRITICAL: Raspberry Pi OS's Firefox build sets media.webrtc.camera.allow-pipewire=true
// in its distribution.ini, routing camera capture through the xdg-desktop-portal Camera
// interface — which has no backend on this labwc setup, so capture is denied (and the
// same portal path hangs Chromium entirely). Force direct V4L2 capture instead.
user_pref("media.webrtc.camera.allow-pipewire", false);

// Auto-grant camera/mic without prompting (meet.jit.si is also allowlisted via
// /etc/firefox/policies/policies.json as a second layer).
user_pref("media.navigator.permission.disabled", true);
user_pref("permissions.default.camera", 1);
user_pref("permissions.default.microphone", 1);

// Autoplay must work without user gesture (remote-triggered call).
user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 0);

// Kiosk hygiene: no first-run tour, no default-browser nag, no crash-restore prompts.
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("toolkit.startup.max_resumed_crashes", -1);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("browser.startup.couldRestoreSession.count", -1);
user_pref("browser.startup.page", 0);
