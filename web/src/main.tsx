import "./styles.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { FeederProvider } from "./state/feeder";

const qc = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
});

createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={qc}>
    <FeederProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </FeederProvider>
  </QueryClientProvider>
);
