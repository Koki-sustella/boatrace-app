import "./style.css";
import { registerSW } from "virtual:pwa-register";
import { route, setNotFound, startRouter, navigate } from "./lib/router";

// The plain auto-injected registration script only calls
// navigator.serviceWorker.register() once -- it never checks for updates or
// reloads when a new version activates, so a visitor can get stuck on a
// stale cached build indefinitely. Registering explicitly here lets us force
// an immediate, silent update: check periodically, and reload as soon as a
// new service worker takes control (no user prompt, matching "autoUpdate").
const intervalMS = 60 * 60 * 1000; // re-check hourly while the app is open
const updateSW = registerSW({
  immediate: true,
  onRegisteredSW(_url, registration) {
    if (!registration) return;
    setInterval(() => registration.update(), intervalMS);
  },
  onNeedRefresh() {
    updateSW(true);
  },
});
import { renderSearchPage } from "./pages/search";
import { renderPlayerPage } from "./pages/player";
import { renderHistoryPage } from "./pages/history";
import { renderVenueCoursePage } from "./pages/venueCourse";
import { renderRankingPage } from "./pages/ranking";
import { renderRaceComparePage } from "./pages/raceCompare";

route("/", () => navigate("/search"));
route("/search", renderSearchPage);
route("/player/:torokuNo", renderPlayerPage);
route("/player/:torokuNo/history", renderHistoryPage);
route("/venue-course", renderVenueCoursePage);
route("/ranking", renderRankingPage);
route("/race-compare", renderRaceComparePage);

setNotFound(() => navigate("/search"));

startRouter();
