import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { ConversationsPage } from "./ChatPage";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import "./styles.css";

const queryClient = new QueryClient();

function ConversationsRoute() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="min-h-screen bg-app-bg text-app-text">
          <div className="flex min-h-screen">
            <Sidebar />
            <div className="min-w-0 flex-1">
              <Topbar />
              <main className="px-4 py-8 lg:px-9">
                <ConversationsPage />
              </main>
            </div>
          </div>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {window.location.pathname === "/conversations" ? <ConversationsRoute /> : <App />}
  </StrictMode>
);
