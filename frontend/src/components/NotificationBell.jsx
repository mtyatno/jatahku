import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';

export default function NotificationBell() {
  const [count, setCount] = useState(0);
  const [notifs, setNotifs] = useState([]);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const navigate = useNavigate();

  const loadCount = async () => {
    const res = await api.request('/notifications/unread-count');
    if (res.ok) {
      const data = await res.json();
      setCount(data.count);
    }
  };

  const loadNotifs = async () => {
    const res = await api.request('/notifications/?limit=10');
    if (res.ok) {
      const data = await res.json();
      setNotifs(data);
    }
  };

  useEffect(() => {
    loadCount();
    const interval = setInterval(loadCount, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const handleClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const handleOpen = () => {
    setOpen(!open);
    if (!open) loadNotifs();
  };

  const handleRead = async (notif) => {
    if (!notif.is_read) {
      await api.request(`/notifications/${notif.id}/read`, { method: 'POST' });
      setCount(c => Math.max(0, c - 1));
      setNotifs(prev => prev.map(n => n.id === notif.id ? { ...n, is_read: true } : n));
    }
    if (notif.link) {
      navigate(notif.link);
      setOpen(false);
    }
  };

  const handleReadAll = async () => {
    await api.request('/notifications/read-all', { method: 'POST' });
    setCount(0);
    setNotifs(prev => prev.map(n => ({ ...n, is_read: true })));
  };

  const timeAgo = (dateStr) => {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'baru saja';
    if (mins < 60) return `${mins} menit lalu`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours} jam lalu`;
    const days = Math.floor(hours / 24);
    return `${days} hari lalu`;
  };

  const typeIcon = (type) => {
    const icons = {
      budget_warning: '⚠️',
      subscription_due: '🔔',
      daily_summary: '📋',
      weekly_summary: '📊',
      cooling_ready: '⏳',
      system: '💬',
    };
    return icons[type] || '💬';
  };

  return (
    <div className="relative" ref={ref}>
      <button onClick={handleOpen} className="relative p-2 rounded-lg hover:bg-gray-50 transition-colors">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-gray-500">
          <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/>
          <path d="M13.73 21a2 2 0 01-3.46 0"/>
        </svg>
        {count > 0 && (
          <span className="absolute -top-0.5 -right-0.5 w-5 h-5 bg-red-500 text-white text-xs font-bold rounded-full flex items-center justify-center">
            {count > 9 ? '9+' : count}
          </span>
        )}
      </button>

      {open && (
        <div className="fixed md:absolute inset-x-2 md:inset-x-auto md:right-0 top-16 md:top-12 md:w-80 bg-white rounded-xl shadow-lg border border-gray-100 z-50 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-50">
            <h3 className="font-semibold text-sm">Notifikasi</h3>
            {count > 0 && (
              <button onClick={handleReadAll} className="text-xs text-brand-600 hover:underline">
                Tandai semua dibaca
              </button>
            )}
          </div>
          <div className="max-h-80 overflow-y-auto">
            {notifs.length === 0 ? (
              <div className="text-center py-8 text-gray-400 text-sm">Belum ada notifikasi</div>
            ) : (
              notifs.map(n => (
                <button key={n.id} onClick={() => handleRead(n)}
                  className={`w-full text-left px-4 py-3 border-b border-gray-50 hover:bg-gray-50 transition-colors flex gap-3 ${!n.is_read ? 'bg-brand-50/30' : ''}`}>
                  <span className="text-lg flex-shrink-0 mt-0.5">{typeIcon(n.type)}</span>
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm ${!n.is_read ? 'font-semibold' : 'font-medium text-gray-600'}`}>{n.title}</p>
                    <p className="text-xs text-gray-400 mt-0.5 truncate">{n.message}</p>
                    <p className="text-xs text-gray-300 mt-1">{timeAgo(n.created_at)}</p>
                  </div>
                  {!n.is_read && <span className="w-2 h-2 bg-brand-400 rounded-full flex-shrink-0 mt-2"/>}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
