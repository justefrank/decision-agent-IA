/** Coque de l'application : navigation latérale (repliée en tiroir sur mobile), contenu, thème, session. */
import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router';

import { hasRole, useAuth } from '@/auth/useAuth';
import { IconButton, Icon } from '@/shared/ui';

import { Logo } from './Logo';
import { ADMIN_NAV, MAIN_NAV, ROLE_LABEL, type NavItem } from './nav';
import { SessionWarning } from './SessionWarning';
import { applyTheme, effectiveTheme, readTheme, type Theme } from './theme';

import './shell.css';

function NavList({ items, label }: { items: NavItem[]; label: string }) {
  const { me } = useAuth();
  const visible = items.filter((i) => hasRole(me?.role, i.roles));
  if (!visible.length) return null;
  return (
    <div className="nav-group">
      <p className="nav-group-label" id={`nav-${label}`}>
        {label}
      </p>
      <ul aria-labelledby={`nav-${label}`}>
        {visible.map((i) => (
          <li key={i.to}>
            <NavLink to={i.to} end={i.end} className="nav-link">
              <Icon name={i.icon} />
              <span>{i.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Shell() {
  const { me, logout } = useAuth();
  const [theme, setTheme] = useState<Theme>(readTheme);
  // Le menu mobile se referme de lui-même au changement de page (ouvert pour un chemin donné).
  const location = useLocation();
  const [openAt, setOpenAt] = useState<string | null>(null);
  const menuOpen = openAt === location.pathname;
  const setMenuOpen = (fn: (o: boolean) => boolean) => setOpenAt(fn(menuOpen) ? location.pathname : null);

  useEffect(() => applyTheme(theme), [theme]);

  const dark = effectiveTheme(theme) === 'dark';

  return (
    <div className="shell" data-menu-open={menuOpen}>
      <a className="skip-link" href="#contenu">
        Aller au contenu
      </a>
      <header className="topbar">
        <IconButton
          icon={menuOpen ? 'close' : 'menu'}
          label={menuOpen ? 'Fermer le menu' : 'Ouvrir le menu'}
          aria-expanded={menuOpen}
          aria-controls="navigation"
          onClick={() => setMenuOpen((o) => !o)}
        />
        <Logo subtitle={false} />
      </header>
      <nav id="navigation" className="sidebar" aria-label="Navigation principale">
        <div className="sidebar-brand">
          <Logo />
        </div>
        <NavList items={MAIN_NAV} label="Analyse" />
        <NavList items={ADMIN_NAV} label="Administration" />
        <div className="sidebar-foot">
          <div className="whoami">
            <Icon name="user" />
            <div>
              <p className="whoami-name">{me?.name ?? me?.email ?? me?.sub}</p>
              <p className="whoami-role">{me ? ROLE_LABEL[me.role] : ''}</p>
            </div>
          </div>
          <div className="sidebar-actions">
            <IconButton
              icon={dark ? 'sun' : 'moon'}
              label={dark ? 'Passer en thème clair' : 'Passer en thème sombre'}
              onClick={() => setTheme(dark ? 'light' : 'dark')}
            />
            <IconButton icon="logout" label="Se déconnecter" onClick={() => void logout()} />
          </div>
        </div>
      </nav>
      <main id="contenu" className="content" tabIndex={-1}>
        <Outlet />
      </main>
      <SessionWarning />
    </div>
  );
}
