import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'
import { wakeServer } from './api/client'

// Start waking the backend now (Render free tier cold start) rather than
// when the user submits the login form. Non-blocking.
void wakeServer()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
