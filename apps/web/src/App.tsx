import { lazy, Suspense, type ReactNode } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import type { Role } from './api/types';
import { AuthProvider, useAuth } from './auth/AuthContext';
import Shell from './components/Shell';
import { Spinner } from './components/ui';
import { homeFor } from './lib/roles';
import Login from './pages/Login';
import Verify from './pages/Verify';

// Heavy routes are lazy-loaded (map + three.js) to keep the shell small for low-bandwidth users.
const Control = lazy(() => import('./pages/Control'));
const Operator = lazy(() => import('./pages/Operator'));
const Transporter = lazy(() => import('./pages/Transporter'));
const Driver = lazy(() => import('./pages/Driver'));
const Owner = lazy(() => import('./pages/Owner'));
const Warehouse = lazy(() => import('./pages/Warehouse'));
const Admin = lazy(() => import('./pages/Admin'));
const Twin = lazy(() => import('./pages/Twin'));

function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  const loc = useLocation();
  if (!session) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  if (session.mfa_required && loc.pathname !== '/login') return <Navigate to="/login" state={{ from: loc.pathname, mfa: true }} replace />;
  if (loading) return <div className="p-8"><Spinner label="Signing in" /></div>;
  return <>{children}</>;
}

function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { hasRole, roles: mine } = useAuth();
  if (roles.length && !hasRole(...roles)) {
    return (
      <div className="card mx-auto mt-10 max-w-lg p-6 text-center">
        <h1 className="text-lg font-semibold">Access restricted</h1>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">Your roles ({mine.join(', ') || 'none'}) do not include one of: {roles.join(', ')}.</p>
        <a className="btn-primary mt-4" href={homeFor(mine)}>Go to my dashboard</a>
      </div>
    );
  }
  return <>{children}</>;
}

function Home() {
  const { roles } = useAuth();
  return <Navigate to={homeFor(roles)} replace />;
}

function NotFound() {
  return <div className="card mx-auto mt-10 max-w-md p-6 text-center"><h1 className="text-lg font-semibold">Page not found</h1><a href="/" className="btn-secondary mt-4">Home</a></div>;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Suspense fallback={<div className="p-8"><Spinner label="Loading module" /></div>}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/verify/:qrToken" element={<Verify />} />
            <Route path="/verify" element={<Verify />} />
            <Route element={<RequireAuth><Shell /></RequireAuth>}>
              <Route index element={<Home />} />
              <Route path="/control" element={<RequireRole roles={['port_controller', 'auditor', 'regulator_readonly']}><Control /></RequireRole>} />
              <Route path="/operator" element={<RequireRole roles={['weighbridge_operator']}><Operator /></RequireRole>} />
              <Route path="/transporter" element={<RequireRole roles={['transporter_admin', 'dispatcher']}><Transporter /></RequireRole>} />
              <Route path="/driver" element={<RequireRole roles={['driver']}><Driver /></RequireRole>} />
              <Route path="/owner" element={<RequireRole roles={['cargo_owner']}><Owner /></RequireRole>} />
              <Route path="/warehouse" element={<RequireRole roles={['warehouse_manager']}><Warehouse /></RequireRole>} />
              <Route path="/admin" element={<RequireRole roles={['platform_admin']}><Admin /></RequireRole>} />
              <Route path="/twin" element={<RequireRole roles={['port_controller', 'weighbridge_operator', 'auditor', 'regulator_readonly', 'transporter_admin', 'dispatcher']}><Twin /></RequireRole>} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </Suspense>
      </BrowserRouter>
    </AuthProvider>
  );
}
