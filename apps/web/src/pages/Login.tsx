import { type FormEvent, useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { ErrorBanner, Field, Notice } from '../components/ui';
import { homeFor } from '../lib/roles';

export default function Login() {
  const { session, login, verifyMfa, roles } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const from = (loc.state as { from?: string } | null)?.from;
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'credentials' | 'mfa'>(session?.mfa_required ? 'mfa' : 'credentials');
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  if (session && !session.mfa_required) return <Navigate to={from && from !== '/login' ? from : homeFor(roles)} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      if (step === 'credentials') {
        const t = await login(email.trim(), password, undefined, remember);
        if (t.mfa_required) setStep('mfa');
        else nav(from && from !== '/login' ? from : homeFor(t.roles), { replace: true });
      } else {
        const t = await verifyMfa(code.trim());
        nav(from && from !== '/login' ? from : homeFor(t.roles), { replace: true });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, (err as Error).message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-8">
      <div className="card w-full max-w-sm p-6">
        <div className="mb-4 flex items-center gap-2">
          <img src="/favicon.svg" alt="" width="32" height="32" />
          <div>
            <h1 className="text-lg font-semibold leading-tight">KIFARU <span className="text-brand-600 dark:text-brand-400">PORTOS</span></h1>
            <p className="text-xs text-slate-500">Rolling clearance platform · sign in</p>
          </div>
        </div>
        <form onSubmit={submit} className="space-y-3" aria-describedby={error ? 'login-error' : undefined}>
          {step === 'credentials' ? (
            <>
              <Field label="Email" required>{(id) => <input id={id} className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
              <Field label="Password" required>{(id) => <input id={id} className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 rounded" checked={remember} onChange={(e) => setRemember(e.target.checked)} />Remember this device (installed app)</label>
            </>
          ) : (
            <>
              <Notice>Your role requires multi-factor authentication. Enter the 6-digit code from your authenticator app.</Notice>
              <Field label="MFA code" required>{(id) => <input id={id} className="input text-center text-lg tracking-widest" inputMode="numeric" pattern="[0-9]{6,8}" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} autoFocus />}</Field>
            </>
          )}
          {error && <div id="login-error"><ErrorBanner error={error.status === 401 && step === 'credentials' ? 'Invalid email or password' : error} /></div>}
          <button className="btn-primary w-full" disabled={busy} type="submit">{busy ? 'Please wait…' : step === 'credentials' ? 'Sign in' : 'Verify code'}</button>
          {step === 'mfa' && <button type="button" className="btn-ghost w-full text-xs" onClick={() => { setStep('credentials'); setCode(''); }}>Back</button>}
        </form>
        <p className="mt-4 text-center text-xs text-slate-500">
          Have a weighing ticket QR? <a className="underline" href="/verify">Verify a ticket</a> without signing in.
        </p>
      </div>
    </main>
  );
}
