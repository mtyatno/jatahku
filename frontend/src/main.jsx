import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import { ThemeProvider } from './hooks/useTheme';
import { native } from './native';

// Lapisan native siap dulu (web: daftarkan service worker; aplikasi: muat token
// dari Keystore/Keychain), baru UI dirender.
native.init().finally(() => {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <ThemeProvider>
        <App />
      </ThemeProvider>
    </React.StrictMode>
  );
});
