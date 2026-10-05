import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { useTheme } from '../hooks/useTheme';

const GSI_SRC = 'https://accounts.google.com/gsi/client';
let gsiPromise = null;

function loadGsi() {
  if (window.google?.accounts?.id) return Promise.resolve();
  if (!gsiPromise) {
    gsiPromise = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = GSI_SRC;
      s.async = true;
      s.onload = resolve;
      s.onerror = () => { gsiPromise = null; reject(); };
      document.head.appendChild(s);
    });
  }
  return gsiPromise;
}

// Renders nothing until the backend has a Google client ID configured.
export default function GoogleButton({ onCredential, text = 'continue_with', divider, clientId: givenClientId }) {
  const ref = useRef(null);
  const callbackRef = useRef(onCredential);
  const { mode } = useTheme();
  const [clientId, setClientId] = useState(givenClientId ?? null);
  callbackRef.current = onCredential;

  useEffect(() => {
    if (givenClientId === undefined) api.getGoogleClientId().then(setClientId);
  }, [givenClientId]);

  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;
    loadGsi().then(() => {
      if (cancelled || !ref.current) return;
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: (resp) => callbackRef.current(resp.credential),
      });
      ref.current.innerHTML = '';
      window.google.accounts.id.renderButton(ref.current, {
        type: 'standard',
        theme: mode === 'dark' ? 'filled_black' : 'outline',
        size: 'large',
        shape: 'pill',
        text,
        locale: 'id',
        width: Math.min(ref.current.offsetWidth || 320, 400),
      });
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [clientId, mode, text]);

  if (!clientId) return null;
  return (
    <>
      <div ref={ref} className="w-full flex justify-center min-h-[44px]" />
      {divider && (
        <div className="flex items-center gap-3 my-4 text-xs text-gray-400">
          <div className="flex-1 border-t border-gray-100" />
          {divider}
          <div className="flex-1 border-t border-gray-100" />
        </div>
      )}
    </>
  );
}
