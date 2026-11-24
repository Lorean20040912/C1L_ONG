import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { ChangeInitialPasswordPage } from "./pages/ChangeInitialPasswordPage";
import { LoginPage } from "./pages/LoginPage";
import { MyBasesPage } from "./pages/MyBasesPage";
import { AppShell } from "./shell/AppShell";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <p className="muted" style={{ padding: 16 }}>Se încarcă…</p>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (user.must_change_password) return <ChangeInitialPasswordPage />;
  return <>{children}</>;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <MyBasesPage />
          </RequireAuth>
        }
      />
      <Route
        path="/org/:orgId"
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
