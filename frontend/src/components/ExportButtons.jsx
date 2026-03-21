import { useState } from 'react';
import { api } from '../lib/api';

export default function ExportButtons() {
  const [loading, setLoading] = useState(null);
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1;
  const monthName = now.toLocaleString('id-ID', { month: 'long', year: 'numeric' });

  const handleExport = async (format) => {
    setLoading(format);
    try {
      const res = await api.request("/export/" + format + "?year=" + year + "&month=" + month);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      if (format === "pdf") {
        window.open(url, "_blank");
      } else {
        const a = document.createElement("a");
        a.href = url;
        a.download = "jatahku_" + year + "-" + String(month).padStart(2, "0") + "." + format;
        a.click();
      }
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e);
    }
    setLoading(null);
  };

  return (
    <div className="flex items-center gap-3">
      <button onClick={() => handleExport("csv")} disabled={!!loading}
        className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 rounded-xl text-sm font-medium text-gray-600 hover:border-brand-400 hover:text-brand-600 transition-all disabled:opacity-50">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        {loading === "csv" ? "..." : "Download CSV"}
      </button>
      <button onClick={() => handleExport("pdf")} disabled={!!loading}
        className="flex items-center gap-2 px-4 py-2 bg-brand-600 rounded-xl text-sm font-medium text-white hover:bg-brand-900 transition-all disabled:opacity-50">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
        {loading === "pdf" ? "..." : "Laporan " + monthName}
      </button>
    </div>
  );
}
