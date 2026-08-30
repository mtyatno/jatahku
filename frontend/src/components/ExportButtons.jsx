import { useState, useRef, useEffect } from 'react';
import { api } from '../lib/api';
import {
  buildExportCsvUrl,
  buildExportPdfUrl,
  getExportFilename,
  getExportButtonLabel,
  resolveActivePeriod,
} from '../lib/exportPeriod';

export default function ExportButtons({ periodStart, periodEnd, periodLabel }) {
  const [periods, setPeriods] = useState([]);
  const [loading, setLoading] = useState(null);
  const [pdfUrl, setPdfUrl] = useState(null);
  const [modalPeriodIdx, setModalPeriodIdx] = useState(null);
  const iframeRef = useRef(null);

  useEffect(() => {
    api.getPeriods(12).then(p => {
      if (Array.isArray(p)) setPeriods(p);
    }).catch(e => {
      console.error(e);
    });
  }, []);

  const now = new Date();
  const defaultLabel = now.toLocaleString('id-ID', { month: 'long', year: 'numeric' });
  const activePeriod = resolveActivePeriod(periods, { periodStart, periodEnd, periodLabel });
  const displayLabel = periodLabel || activePeriod?.label || defaultLabel;
  const buttonLabel = getExportButtonLabel(displayLabel);

  const handleCSV = async () => {
    setLoading('csv');
    try {
      const target = activePeriod || (periodStart && periodEnd ? { period_start: periodStart, period_end: periodEnd } : null);
      const url = buildExportCsvUrl(target);
      const res = await api.request(url);
      if (res.ok) {
        const blob = await res.blob();
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = getExportFilename('csv', target);
        a.click();
        URL.revokeObjectURL(blobUrl);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(null);
    }
  };

  const openReportForPeriod = async (targetPeriod, idx = null) => {
    if (!targetPeriod && !periodStart) return;
    const target = targetPeriod || (periodStart && periodEnd ? { period_start: periodStart, period_end: periodEnd, label: periodLabel } : null);
    setLoading('pdf');
    try {
      const url = buildExportPdfUrl(target);
      const res = await api.request(url);
      if (res.ok) {
        const blob = await res.blob();
        const blobUrl = URL.createObjectURL(blob);
        if (pdfUrl) URL.revokeObjectURL(pdfUrl);
        setPdfUrl(blobUrl);
        if (idx !== null) {
          setModalPeriodIdx(idx);
        } else if (target?.period_start && target?.period_end) {
          const foundIdx = periods.findIndex(
            p => p.period_start === target.period_start && p.period_end === target.period_end
          );
          setModalPeriodIdx(foundIdx >= 0 ? foundIdx : (periods.length > 0 ? periods.length - 1 : null));
        } else if (periods.length > 0) {
          setModalPeriodIdx(periods.length - 1);
        } else {
          setModalPeriodIdx(null);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(null);
    }
  };

  const curModalPeriod = (modalPeriodIdx !== null && periods[modalPeriodIdx])
    ? periods[modalPeriodIdx]
    : (activePeriod || (periodStart && periodEnd ? { period_start: periodStart, period_end: periodEnd, label: periodLabel } : null));

  const goPrev = () => {
    if (modalPeriodIdx === null || modalPeriodIdx <= 0) return;
    const prevIdx = modalPeriodIdx - 1;
    openReportForPeriod(periods[prevIdx], prevIdx);
  };

  const goNext = () => {
    if (modalPeriodIdx === null || modalPeriodIdx >= periods.length - 1) return;
    const nextIdx = modalPeriodIdx + 1;
    openReportForPeriod(periods[nextIdx], nextIdx);
  };

  const handleSavePDF = () => {
    if (pdfUrl) {
      const a = document.createElement('a');
      a.href = pdfUrl;
      a.download = getExportFilename('pdf', curModalPeriod);
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
    if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    setPdfUrl(null);
    setModalPeriodIdx(null);
  };

  return (
    <>
      <div className="flex items-center gap-3">
        <button
          onClick={handleCSV}
          disabled={!!loading}
          className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 rounded-xl text-sm font-medium text-gray-600 hover:border-brand-400 hover:text-brand-600 transition-all disabled:opacity-50"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          {loading === 'csv' ? '...' : 'Download CSV'}
        </button>
        <button
          onClick={() => openReportForPeriod(activePeriod)}
          disabled={!!loading}
          className="flex items-center gap-2 px-4 py-2 bg-brand-600 rounded-xl text-sm font-medium text-white hover:bg-brand-900 transition-all disabled:opacity-50"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
          {loading === 'pdf' ? '...' : buttonLabel}
        </button>
      </div>

      {/* Report Modal */}
      {pdfUrl && (
        <div className="fixed inset-0 z-50 flex flex-col bg-white">
          {/* Toolbar */}
          <div className="flex items-center justify-between px-4 py-3 bg-white border-b border-gray-200 shrink-0">
            {/* Month / Period navigator */}
            <div className="flex items-center gap-1 bg-gray-100 rounded-xl px-1 py-1">
              <button
                onClick={goPrev}
                disabled={!periods.length || modalPeriodIdx === null || modalPeriodIdx <= 0 || !!loading}
                className="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-white text-gray-500 hover:text-gray-700 transition-all disabled:opacity-30 disabled:cursor-default"
                aria-label="Periode sebelumnya"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
              <span className="text-sm font-semibold text-gray-700 px-2 min-w-[130px] text-center">
                {loading === 'pdf' ? '...' : (curModalPeriod?.label || displayLabel)}
              </span>
              <button
                onClick={goNext}
                disabled={!periods.length || modalPeriodIdx === null || modalPeriodIdx >= periods.length - 1 || !!loading}
                className="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-white text-gray-500 hover:text-gray-700 transition-all disabled:opacity-30 disabled:cursor-default"
                aria-label="Periode berikutnya"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </button>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={handleSavePDF}
                disabled={!!loading}
                className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 rounded-lg text-sm font-medium text-gray-600 hover:border-brand-400 hover:text-brand-600 transition-all disabled:opacity-50"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                </svg>
                Simpan PDF
              </button>
              <button
                onClick={handlePrint}
                disabled={!!loading}
                className="flex items-center gap-2 px-4 py-2 bg-brand-600 rounded-lg text-sm font-medium text-white hover:bg-brand-900 transition-all disabled:opacity-50"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <polyline points="6 9 6 2 18 2 18 9" />
                  <path d="M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2" />
                  <rect x="6" y="14" width="12" height="8" />
                </svg>
                Print
              </button>
              <button
                onClick={handleClose}
                className="flex items-center justify-center w-9 h-9 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-all"
                aria-label="Tutup laporan"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          </div>

          {/* PDF Viewer */}
          <iframe
            ref={iframeRef}
            src={pdfUrl}
            className="flex-1 w-full border-0"
            title="Laporan Keuangan"
          />
        </div>
      )}
    </>
  );
}
