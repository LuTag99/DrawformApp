import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  HiSparkles,
  HiOutlineCubeTransparent,
  HiOutlineChartPie,
  HiOutlineArrowUpTray,
  HiOutlineUserCircle,
} from 'react-icons/hi2';
import './AppShell.css';
import { GradientButton } from '../components/GradientButton';
import { useAuth } from '../hooks/useAuth';

const navLinks = [
  { to: '/', label: 'Dashboard', icon: HiSparkles },
  { to: '/analyzer', label: 'Bemaßung', icon: HiOutlineCubeTransparent },
  { to: '/projects', label: 'Projekte', icon: HiOutlineChartPie },
  { to: '/export', label: 'Export', icon: HiOutlineArrowUpTray },
  { to: '/profile', label: 'Profil', icon: HiOutlineUserCircle },
];

export function AppShell() {
  const { user, logout } = useAuth();
  const initials = user?.email?.substring(0, 2)?.toUpperCase() ?? 'DF';

  return (
    <div className="content-layer">
      <div className="app-shell">
        <aside className="app-shell__sidebar glass-panel">
          <div className="sidebar__quick">
            <div className="sidebar__brand">
              <span>Drawform AI</span>
            </div>
            <div className="sidebar__avatar">
              {user?.avatarUrl ? (
                <img src={user.avatarUrl} alt="Profil" />
              ) : (
                <div className="fallback">{initials}</div>
              )}
              <div>
                <strong>{user?.email ?? 'Willkommen'}</strong>
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
          <GradientButton
            label="Logout"
            onClick={logout}
            style={{ width: '100%' }}
          />
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
