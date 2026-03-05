import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import HomePage from "./pages/viewer/HomePage";
import LoginPage from "./pages/admin/LoginPage";
import AdminLayout from "./pages/admin/AdminLayout";
import UploadPage from "./pages/admin/UploadPage";
import PresentationsPage from "./pages/admin/PresentationsPage";
import LogsPage from "./pages/admin/LogsPage";
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public viewer routes */}
        <Route path="/" element={<HomePage />} />

        {/* Admin routes */}
        <Route path="/admin/login" element={<LoginPage />} />
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<Navigate to="upload" replace />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="presentations" element={<PresentationsPage />} />
          <Route path="logs" element={<LogsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
