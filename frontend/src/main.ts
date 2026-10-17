import "./style.css";
import { route, setNotFound, startRouter, navigate } from "./lib/router";
import { renderSearchPage } from "./pages/search";
import { renderPlayerPage } from "./pages/player";
import { renderHistoryPage } from "./pages/history";
import { renderVenueCoursePage } from "./pages/venueCourse";
import { renderRankingPage } from "./pages/ranking";

route("/", () => navigate("/search"));
route("/search", renderSearchPage);
route("/player/:torokuNo", renderPlayerPage);
route("/player/:torokuNo/history", renderHistoryPage);
route("/venue-course", renderVenueCoursePage);
route("/ranking", renderRankingPage);

setNotFound(() => navigate("/search"));

startRouter();
