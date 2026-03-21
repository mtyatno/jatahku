import { useState } from 'react';
import { api } from '../lib/api';

export default function ExportButtons() {
  const [loading, setLoading] = useState(false);
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1;

  const handleExport = async (format) => {
    setLoading(true);
    try {
      const res = await api.request(`/export/${format}?year=${year}&month=${month}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      if (format === 'pdf') {
        window.open(url, '_blank');
      } else {
        const a = document.createElement('a');
        a.href = url;
        a.download = `jatahku_${year}-${String(month).padStart(2,'0')}.${format}`;
        a.click();
      }
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  return (
    <div className="flex gap-2">
      <button onClick={() => handleExport('csv')} disabled={loading}
        className="text-xs font-medium text-brand-600 hover:underline disabled:opacity-50">
        📥 CSV
      </button>
      <button onClick={() => handleExport('pdf')} disabled={loading}
        className="text-xs font-medium text-brand-600 hover:underline disabled:opacity-50">
        📄 Laporan
      </button>
    </div>
  );
}
