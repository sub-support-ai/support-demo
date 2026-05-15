import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { ShellLayout } from "./components/layout/ShellLayout";
import { useAuth } from "./stores/auth";

const LoginPage = lazy(() => import("./pages/LoginPage").then(m => ({ default: m.LoginPage })));
const DashboardPage = lazy(() => import("./pages/DashboardPage").then(m => ({ default: m.DashboardPage })));
const ChatPage = lazy(() => import("./pages/ChatPage").then(m => ({ default: m.ChatPage })));
const TicketsPage = lazy(() => import("./pages/TicketsPage").then(m => ({ default: m.TicketsPage })));
const KnowledgePage = lazy(() => import("./pages/KnowledgePage").then(m => ({ default: m.KnowledgePage })));
const JobsPage = lazy(() => import("./pages/JobsPage").then(m => ({ default: m.JobsPage })));

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token } = useAuth();
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export function App() {
  return (
    <Suspense fallback={<div style={{ padding: "2rem" }}>Загрузка...</div>}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <ShellLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="tickets" element={<TicketsPage />} />
          <Route path="knowledge" element={<KnowledgePage />} />
          <Route path="jobs" element={<JobsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}