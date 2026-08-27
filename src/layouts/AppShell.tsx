import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  HiSparkles,
  HiOutlineCubeTransparent,
  HiOutlineChartPie,
  HiOutlineArrowUpTray,
  HiOutlineCube,
} from 'react-icons/hi2';
import './AppShell.css';

const navLinks = [
  { to: '/', label: 'Dashboard', icon: HiSparkles },
  { to: '/analyzer', label: 'Bemaßung', icon: HiOutlineCubeTransparent },
  { to: '/reconstruct', label: 'Rekonstruktion', icon: HiOutlineCube },
  { to: '/projects', label: 'Projekte', icon: HiOutlineChartPie },
  { to: '/export', label: 'Export', icon: HiOutlineArrowUpTray },
];

export function AppShell() {
  return (
    <div className="content-layer">
      <div className="app-shell">
        <aside className="app-shell__sidebar glass-panel">
          <div className="sidebar__quick">
            <div className="sidebar__brand">
              <span>Drawform AI</span>
            </div>
            <div className="sidebar__avatar">
              <div className="fallback">DF</div>
              <div>
                <strong>Drawform Workspace</strong>
                <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
                  AI Design Workspace
                </p>
              </div>
            </div>
            <nav className="sidebar__nav">
              {navLinks.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    ['nav-link', isActive && 'nav-link--active']
                      .filter(Boolean)
                      .join(' ')
                  }
                  end={item.to === '/'}
                >
                  <item.icon />
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
        </aside>
        <main className="app-shell__main">
          <Outlet />
        </main>
      </div>
      <MobileNav />
    </div>
  );
}

function MobileNav() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <div className="mobile-nav glass-panel--soft">
      {navLinks.map((item) => {
        const isActive = location.pathname === item.to;
        return (
          <button
            key={item.to}
            type="button"
            className={isActive ? 'active' : undefined}
            onClick={() => navigate(item.to)}
          >
            <item.icon />
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

export default AppShell;
