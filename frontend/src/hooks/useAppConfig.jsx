import { createContext, useContext, useEffect, useState } from 'react';
import { api } from '../lib/api';
import { initialConfig, refreshAppConfig, DEFAULT_CONFIG } from '../lib/appConfig';
import { CLIENT_HEADER_VALUE } from '../lib/clientInfo';
import { createErrorReporter, installErrorReporter } from '../lib/errorReporter';

const AppConfigContext = createContext(DEFAULT_CONFIG);

// Nilai terakhir untuk pelapor error (dipanggil di luar siklus render).
const configRef = { current: DEFAULT_CONFIG };

// Dipasang sekali di Layout: render pertama memakai cache, lalu config
// diperbarui di latar (saat dibuka dan saat tab kembali terlihat, paling
// cepat tiap CONFIG_TTL_MS). Juga memasang pelapor error klien.
export function useAppConfigLoader() {
  const [config, setConfig] = useState(() => initialConfig({ client: CLIENT_HEADER_VALUE }));

  useEffect(() => {
    let alive = true;
    const refresh = () => refreshAppConfig({ fetchConfig: () => api.getAppConfig(), client: CLIENT_HEADER_VALUE })
      .then(c => { if (alive) setConfig(c); });
    refresh();
    const onVisible = () => { if (document.visibilityState === 'visible') refresh(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => { alive = false; document.removeEventListener('visibilitychange', onVisible); };
  }, []);

  useEffect(() => {
    const report = createErrorReporter({
      send: (r) => api.reportClientError(r),
      getConfig: () => configRef.current,
    });
    return installErrorReporter(window, report);
  }, []);

  configRef.current = config;
  return config;
}

export const AppConfigProvider = AppConfigContext.Provider;

export function useAppConfig() {
  return useContext(AppConfigContext);
}
