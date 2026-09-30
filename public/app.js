"use strict";

async function checkHealth() {
  const status = document.getElementById("server-status");
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error(response.statusText);
    status.textContent = "Server töötab";
    status.className = "status ok";
  } catch {
    status.textContent = "Server ei vasta";
    status.className = "status error";
  }
}

checkHealth();
