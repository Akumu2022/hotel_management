import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { Skeleton } from "./components/ui";
import { CheckoutPage } from "./customer/CheckoutPage";
import { CustomerLayout } from "./customer/CustomerLayout";
import { HomePage } from "./customer/HomePage";
import { HotelPage } from "./customer/HotelPage";
import { OrdersPage } from "./customer/OrdersPage";
import { TrackPage } from "./customer/TrackPage";
import "./index.css";
import "./lib/theme";
import { ApiError, auth } from "./lib/api";

// Staff areas are split out so customers on slow networks never download them.
const LoginPage = lazy(() => import("./pages/LoginPage").then((m) => ({ default: m.LoginPage })));
const PasswordPage = lazy(() => import("./pages/PasswordPage").then((m) => ({ default: m.PasswordPage })));
const HotelLayout = lazy(() => import("./hotel/HotelLayout").then((m) => ({ default: m.HotelLayout })));
const DashboardPage = lazy(() => import("./hotel/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const HotelOrdersPage = lazy(() => import("./hotel/OrdersPage").then((m) => ({ default: m.OrdersPage })));
const PaymentsPage = lazy(() => import("./hotel/PaymentsPage").then((m) => ({ default: m.PaymentsPage })));
const ReviewPage = lazy(() => import("./admin/ReviewPage").then((m) => ({ default: m.ReviewPage })));
const MenuPage = lazy(() => import("./hotel/MenuPage").then((m) => ({ default: m.MenuPage })));
const DiscountsPage = lazy(() => import("./hotel/DiscountsPage").then((m) => ({ default: m.DiscountsPage })));
const OffersPage = lazy(() => import("./hotel/OffersPage").then((m) => ({ default: m.OffersPage })));
const BillingPage = lazy(() => import("./hotel/BillingPage").then((m) => ({ default: m.BillingPage })));
const AdminBillingPage = lazy(() => import("./admin/BillingPage").then((m) => ({ default: m.AdminBillingPage })));
const SettingsPage = lazy(() => import("./hotel/SettingsPage").then((m) => ({ default: m.SettingsPage })));
/** Hotel admins land on the dashboard; cashiers on the order board, where the alarm rings. */
function HotelHome() {
  return <Navigate to={auth.user()?.role === "hotel_admin" ? "dashboard" : "orders"} replace />;
}
const RiderHome = lazy(() => import("./rider/RiderHome").then((m) => ({ default: m.RiderHome })));
const JoinPage = lazy(() => import("./rider/JoinPage").then((m) => ({ default: m.JoinPage })));
const AdminLayout = lazy(() => import("./admin/AdminLayout").then((m) => ({ default: m.AdminLayout })));
const AdminDashboardPage = lazy(() =>
  import("./admin/DashboardPage").then((m) => ({
    default: m.AdminDashboardPage,
  })),
);
const FeesPage = lazy(() => import("./admin/FeesPage").then((m) => ({ default: m.FeesPage })));
const RidersPage = lazy(() => import("./admin/RidersPage").then((m) => ({ default: m.RidersPage })));
const AdminHotelsPage = lazy(() => import("./admin/HotelsPage").then((m) => ({ default: m.HotelsPage })));
const DispatchPage = lazy(() => import("./admin/DispatchPage").then((m) => ({ default: m.DispatchPage })));
const ToolsPage = lazy(() => import("./admin/ToolsPage").then((m) => ({ default: m.ToolsPage })));
const DeliveryPage = lazy(() => import("./admin/DeliveryPage").then((m) => ({ default: m.DeliveryPage })));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (count, error) => !(error instanceof ApiError && error.status > 0 && error.status < 500) && count < 2,
    },
  },
});

const loading = (
  <div className="mx-auto max-w-xl p-4">
    <Skeleton className="h-40" />
  </div>
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Suspense fallback={loading}>
            <Routes>
              <Route element={<CustomerLayout />}>
                <Route index element={<HomePage />} />
                <Route path="h/:slug" element={<HotelPage />} />
                <Route path="checkout" element={<CheckoutPage />} />
                <Route path="o/:token" element={<TrackPage />} />
                <Route path="orders" element={<OrdersPage />} />
              </Route>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/password" element={<PasswordPage />} />
              <Route path="/rider" element={<RiderHome />} />
              <Route path="/rider/join" element={<JoinPage />} />
              <Route path="/hotel" element={<HotelLayout />}>
                <Route index element={<HotelHome />} />
                <Route path="orders" element={<HotelOrdersPage />} />
                <Route path="dashboard" element={<DashboardPage />} />
                <Route path="payments" element={<PaymentsPage />} />
                <Route path="menu" element={<MenuPage />} />
                <Route path="discounts" element={<DiscountsPage />} />
                <Route path="offers" element={<OffersPage />} />
                <Route path="settings" element={<SettingsPage />} />
                <Route path="billing" element={<BillingPage />} />
              </Route>
              <Route path="/admin" element={<AdminLayout />}>
                <Route index element={<Navigate to="dashboard" replace />} />
                <Route path="dashboard" element={<AdminDashboardPage />} />
                <Route path="review" element={<ReviewPage />} />
                <Route path="dispatch" element={<DispatchPage />} />
                <Route path="billing" element={<AdminBillingPage />} />
                <Route path="riders" element={<RidersPage />} />
                <Route path="hotels" element={<AdminHotelsPage />} />
                <Route path="fees" element={<FeesPage />} />
                <Route path="delivery" element={<DeliveryPage />} />
                <Route path="tools" element={<ToolsPage />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);

// Installable app + offline shell. Production only: in development it would cache Vite's modules.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
