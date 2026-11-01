// Bagian Beranda di luar kartu (Plugin B2): periode, streak, papan disiplin, banner perayaan, dan
// panduan onboarding. Dipakai Beranda lama dan Beranda registry supaya keduanya identik.
import { useState, useEffect } from 'react';
import { api } from '../lib/api';

const MILESTONES = [3, 7, 14, 30, 50, 100, 150, 200, 365];

export function useBerandaShell() {
  const [periods, setPeriods] = useState([]);
  const [periodIdx, setPeriodIdx] = useState(null);
  const [streak, setStreak] = useState(null);
  const [leaderboard, setLeaderboard] = useState([]);
  const [celebrate, setCelebrate] = useState(null);
  const [showOnboardingGuide, setShowOnboardingGuide] = useState(false);

  useEffect(() => {
    const mode = sessionStorage.getItem('onboarded_income_mode');
    if (mode === 'daily' || mode === 'weekly') setShowOnboardingGuide(true);
  }, []);

  useEffect(() => {
    api.getPeriods(12).then(p => {
      setPeriods(p);
      setPeriodIdx(p.length - 1);
    });
    api.request('/user/streak').then(r => r.ok ? r.json() : null).then(s => {
      if (!s) return;
      setStreak(s);
      // Celebrate each milestone once per device.
      if (MILESTONES.includes(s.current_streak)) {
        const key = `jatahku_celebrated_${s.current_streak}`;
        if (!localStorage.getItem(key)) {
          setCelebrate(s.current_streak);
          localStorage.setItem(key, '1');
        }
      }
    });
    api.request('/household/leaderboard').then(r => r.ok ? r.json() : []).then(setLeaderboard);
  }, []);

  const isCurrentPeriod = periods.length > 0 && periodIdx === periods.length - 1;
  return {
    periods, periodIdx, setPeriodIdx, isCurrentPeriod, selectedPeriod: periods[periodIdx],
    streak, leaderboard, celebrate, setCelebrate, showOnboardingGuide, setShowOnboardingGuide,
  };
}
