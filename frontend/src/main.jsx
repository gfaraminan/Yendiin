import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { brandConfig } from './config/brand'

document.title = brandConfig.name || 'Ticketera'
const metaDescription = document.querySelector('meta[name=\"description\"]')
if (metaDescription) {
  metaDescription.setAttribute('content', brandConfig.heroSubtitle || 'Plataforma de tickets online.')
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
window.addEventListener("error", (e) => {
  console.error("GLOBAL ERROR:", e.error || e.message);
});
window.addEventListener("unhandledrejection", (e) => {
  console.error("UNHANDLED PROMISE:", e.reason);
});
