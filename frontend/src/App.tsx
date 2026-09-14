import { useEffect, useState } from "react";
import { BrowserRouter, NavLink, Route, Routes, useLocation } from "react-router";
import "./App.css";
import { actorType, loadSession, useSession } from "./api/session";
import { ErrorNotice } from "./components/States";
import { PersonaSwitcher } from "./components/PersonaSwitcher";
import { ThemeToggle } from "./components/ThemeToggle";
import { OperationsBoard } from "./pages/OperationsBoard";
import { IssueDetail } from "./pages/IssueDetail";
import { OperatorInbox } from "./pages/OperatorInbox";
import { CrewJobs } from "./pages/CrewJobs";
import { CrewJob } from "./pages/CrewJob";
import { ResidentIntake } from "./pages/ResidentIntake";

const DISTRICT = "South Loop Demo District";

function NotFound() { return <div className="page"><h1>Page not found</h1><p><NavLink to="/">Back to the board</NavLink></p></div>; }

function Frame() {
  const s = useSession();
  const type = actorType(s);
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => { setOpen(false); }, [location.pathname]);
  const links: Array<[string, string]> = [];
  if (type === "operator") links.push(["/", "Board"], ["/inbox", "Inbox"]);
  if (type === "crew") links.push(["/crew", "Crew"]);
  links.push(["/report", "Report"]);
  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <div className="sandbox-strip"><span><b>Sandbox demo</b> · Seeded district and fixtures</span><span>Dispatch and settlement are simulated</span></div>
      <header className="app-header">
        <div className="app-header__brand">
          <NavLink to="/" className="wordmark">steward<span>.</span></NavLink>
          <span className="district">{DISTRICT}</span>
        </div>
        <button type="button" className="menu-button btn btn--quiet" aria-expanded={open} aria-controls="app-menu" onClick={() => setOpen((v) => !v)}>Menu</button>
        <div id="app-menu" className={`app-menu ${open ? "app-menu--open" : ""}`}>
          <nav className="app-nav" aria-label="Primary">
            {links.map(([to, label]) => <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "is-active" : undefined)}>{label}</NavLink>)}
          </nav>
          <div className="app-controls">
            {!type && s.status === "ready" && <p className="small muted">Select a persona to read or submit anything.</p>}
            <PersonaSwitcher />
            <ThemeToggle />
          </div>
        </div>
      </header>
      {s.status === "error" && <div className="page"><ErrorNotice error={s.error} title="Session unavailable" onRetry={() => void loadSession()} /></div>}
      <main id="main" className="app-main">
        <Routes>
          <Route path="/" element={<OperationsBoard />} />
          <Route path="/issues/:issueId" element={<IssueDetail />} />
          <Route path="/inbox" element={<OperatorInbox />} />
          <Route path="/crew" element={<CrewJobs />} />
          <Route path="/crew/jobs/:jobId" element={<CrewJob />} />
          <Route path="/report" element={<ResidentIntake />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="app-footer small muted">
        Demo personas, seeded fixtures and simulated dispatch and settlement. No real authority or money. <a href="https://github.com/juulsverne/steward">Source</a>
      </footer>
    </>
  );
}

export default function App() {
  useEffect(() => { void loadSession(); }, []);
  return <BrowserRouter><Frame /></BrowserRouter>;
}
