import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import RegionsPage from "./regions/RegionsPage";
import "./styles.css";

type Route = "compare" | "regions";

function currentRoute(): Route {
  return window.location.hash === "#/regions" ? "regions" : "compare";
}

function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(currentRoute);
  useEffect(() => {
    const onChange = () => setRoute(currentRoute());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

function NavBar({ route }: { route: Route }) {
  return (
    <nav className="nav">
      <span className="nav-brand">MasterOCR</span>
      <a href="#/" className={route === "compare" ? "on" : ""}>
        Engine compare
      </a>
      <a href="#/regions" className={route === "regions" ? "on" : ""}>
        Region capture
      </a>
    </nav>
  );
}

function Shell() {
  const route = useHashRoute();
  return (
    <>
      <NavBar route={route} />
      {route === "regions" ? <RegionsPage /> : <App />}
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Shell />
  </React.StrictMode>
);
