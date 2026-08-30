/**
 * Helper utilities for budget period export URL generation, filename building,
 * button labels, and period navigation.
 */

export function buildExportCsvUrl(params = {}) {
  const pStart = params?.periodStart || params?.period_start;
  const pEnd = params?.periodEnd || params?.period_end;
  const envId = params?.envelopeId || params?.envelope_id;
  const q = new URLSearchParams();
  if (pStart) q.set('period_start', pStart);
  if (pEnd) q.set('period_end', pEnd);
  if (envId) q.set('envelope_id', envId);
  const qs = q.toString();
  return `/export/csv${qs ? `?${qs}` : ''}`;
}

export function buildExportPdfUrl(params = {}) {
  const pStart = params?.periodStart || params?.period_start;
  const pEnd = params?.periodEnd || params?.period_end;
  const envId = params?.envelopeId || params?.envelope_id;
  const q = new URLSearchParams();
  if (pStart) q.set('period_start', pStart);
  if (pEnd) q.set('period_end', pEnd);
  if (envId) q.set('envelope_id', envId);
  const qs = q.toString();
  return `/export/pdf${qs ? `?${qs}` : ''}`;
}

export function getExportFilename(type = 'csv', params = {}) {
  const ext = type.toLowerCase() === 'pdf' ? 'pdf' : 'csv';
  const pStart = params?.periodStart || params?.period_start;
  const pEnd = params?.periodEnd || params?.period_end;
  if (pStart && pEnd) {
    return `jatahku_${pStart}_${pEnd}.${ext}`;
  }
  return `jatahku_export.${ext}`;
}

export function getExportButtonLabel(label) {
  const trimmed = (label || '').trim();
  if (!trimmed) return 'Laporan';
  if (trimmed.startsWith('Laporan')) return trimmed;
  return `Laporan ${trimmed}`;
}

export function resolveActivePeriod(periods = [], { periodStart, periodEnd, periodLabel } = {}) {
  if (periodStart && periodEnd) {
    const found = (periods || []).find(
      p => p.period_start === periodStart && p.period_end === periodEnd
    );
    if (found) {
      return {
        ...found,
        label: periodLabel || found.label,
      };
    }
    return {
      period_start: periodStart,
      period_end: periodEnd,
      label: periodLabel || `${periodStart} – ${periodEnd}`,
    };
  }

  if (Array.isArray(periods) && periods.length > 0) {
    const last = periods[periods.length - 1];
    return {
      ...last,
      label: periodLabel || last.label,
    };
  }

  if (periodLabel) {
    return {
      period_start: null,
      period_end: null,
      label: periodLabel,
    };
  }

  return null;
}

export function findPeriodIndex(periods = [], target = {}) {
  if (!Array.isArray(periods) || periods.length === 0 || !target) return -1;
  const pStart = target.periodStart || target.period_start;
  const pEnd = target.periodEnd || target.period_end;
  if (!pStart || !pEnd) return -1;
  return periods.findIndex(p => p.period_start === pStart && p.period_end === pEnd);
}

export function canGoPrev(currentIndex) {
  return typeof currentIndex === 'number' && currentIndex > 0;
}

export function canGoNext(currentIndex, totalPeriods) {
  return typeof currentIndex === 'number' && currentIndex >= 0 && currentIndex < totalPeriods - 1;
}

export function getPrevPeriodIndex(currentIndex) {
  if (typeof currentIndex !== 'number') return -1;
  return Math.max(0, currentIndex - 1);
}

export function getNextPeriodIndex(currentIndex, totalPeriods) {
  if (typeof currentIndex !== 'number' || typeof totalPeriods !== 'number' || totalPeriods <= 0) return -1;
  return Math.min(totalPeriods - 1, currentIndex + 1);
}
