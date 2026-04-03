import { useState, useRef } from 'react';
import { api } from '../lib/api';

export default function ExportButtons() {
  const [loading, setLoading] = useState(null);
  const [pdfUrl, setPdfUrl] = useState(null);
  const iframeRef = useRef(null);

  const now = new Date();
  const [selectedYear, setSelectedYear] = useState(now.getFullYear());
  const [selectedMonth, setSelectedMonth] = useState(now.getMonth() + 1);

  const year = selectedYear;
  const month = selectedMonth;
  const monthName = new Date(selectedYear, selectedMonth - 1, 1).toLocaleString('id-ID', { month: 'long', year: 'numeric' });
  const isCurrentMonth = selectedYear === now.getFullYear() && selectedMonth === now.getMonth() + 1;

  const goPrev = () => {
    if (selectedMonth === 1) { setSelectedMonth(12); setSelectedYear(y => y - 1); }
    else setSelectedMonth(m => m - 1);
  };
  const goNext = () => {
    if (isCurrentMonth) return;
    if (selectedMonth === 12) { setSelectedMonth(1); setSelectedYear(y => y + 1); }
    else setSelectedMonth(m => m + 1);
  };

  const handleCSV = async () => {
    setLoading('csv');
    try {
      const res = await api.request('/export/csv?year=' + year + '&month=' + month);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'jatahku_' + year + '-' + String(month).padStart(2, '0') + '.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e);
    }
    setLoading(null);
  };

  const handleOpenReport = async () => {
    setLoading('pdf');
    try {
      const res = await api.request('/export/pdf?year=' + year + '&month=' + month);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      setPdfUrl(url);
    } catch (e) {
      console.error(e);
    }
    setLoading(null);
  };

  const handleSavePDF = () => {
    if (pdfUrl) {
      const a = document.createElement('a');
      a.href = pdfUrl;
      a.download = 'jatahku_' + year + '-' + String(month).padStart(2, '0') + '.pdf';
      a.click();
    }
  };

  const handlePrint = () => {
    if (iframeRef.current) {
      iframeRef.current.contentWindow.focus();
      iframeRef.current.contentWindow.print();
    }
  };

  const handleClose = () => {
    URL.revokeObjectURL(pdfUrl);
    setPdfUrl(null);
  };

  return (
    <>
      <div className="flex items-center gap-3 flex-wrap">
        {/* Month navigator */}
        <div className="flex items-center gap-1 bg-gray-100 rounded-xl px-1 py-1">
          <button onClick={goPrev} className="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-white text-gray-500 hover:text-gray-700 transition-all">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="15 18 9 12 15 6"/></svg>
          </button>
          <span className="text-sm font-medium text-gray-700 px-2 min-w-[110px] text-center">{monthName}</span>
          <button onClick={goNext} disabled={isCurrentMonth} className="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-white text-gray-500 hover:text-gray-700 transition-all disabled:opacity-30 disabled:cursor-default">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="9 18 15 12 9 6"/></svg>
          </button>
        </div>

        <button onClick={handleCSV} disabled={!!loading}
          className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 rounded-xl text-sm font-medium text-gray-600 hover:border-brand-400 hover:text-brand-600 transition-all disabled:opacity-50">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          {loading === 'csv' ? '...' : 'CSV'}
        </button>
        <button onClick={handleOpenReport} disabled={!!loading}
          className="flex items-center gap-2 px-4 py-2 bg-brand-600 rounded-xl text-sm font-medium text-white hover:bg-brand-900 transition-all disabled:opacity-50">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
          {loading === 'pdf' ? '...' : 'Laporan'}
        </button>
      </div>

      {/* Report Modal */}
      {pdfUrl && (
        <div className="fixed inset-0 z-50 flex flex-col bg-white">
          {/* Toolbar */}
          <div className="flex items-center justify-between px-4 py-3 bg-white border-b border-gray-200 shrink-0">
            <span className="font-semibold text-gray-700">Laporan {monthName}</span>
            <div className="flex items-center gap-2">
              <button onClick={handleSavePDF}
                title="Pilih 'Save as PDF' di dialog print"
                className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 rounded-lg text-sm font-medium text-gray-600 hover:border-brand-400 hover:text-brand-600 transition-all">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                Simpan PDF
              </button>
              <button onClick={handlePrint}
                className="flex items-center gap-2 px-4 py-2 bg-brand-600 rounded-lg text-sm font-medium text-white hover:bg-brand-900 transition-all">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
                Print
              </button>
              <button onClick={handleClose}
                className="flex items-center justify-center w-9 h-9 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-all">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
          </div>

          {/* PDF Viewer */}
          <iframe
            ref={iframeRef}
            src={pdfUrl}
            className="flex-1 w-full border-0"
            title="Laporan Bulanan"
          />
        </div>
      )}
    </>
  );
}
