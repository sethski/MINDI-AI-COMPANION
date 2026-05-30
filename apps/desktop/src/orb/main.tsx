import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MindiOrb } from "../components/orb/MindiOrb";
import "../styles/orb.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MindiOrb />
  </StrictMode>,
);
