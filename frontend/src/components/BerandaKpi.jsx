// Enam kartu KPI Beranda (Plugin B2), dipakai Beranda lama dan Beranda registry supaya tampilan
// dan angkanya sama persis. Semua angka dari `berandaModel` (lib/berandaModel.js); di sini hanya
// memilih teks dan warna. Dua cabang: AI Advisor aktif (`m.adv`, metrik server) dan UI lama.
import { KpiTile, tileTones } from './KpiCard';
import { rpFull, rpCompact, predictionOver, daysLabel, periodDayLabel, periodProgress, savingRateLabel, cashFlowLabel } from '../lib/kpiCards';
import { savingsProgress } from '../lib/kpiVisuals';

export function KpiJatah({ m, isDark, chip }) {
  const tt = tileTones(isDark);
  if (m.adv) {
    const { k, advMeter } = m;
    return (
      <KpiTile
        isDark={isDark} label="Jatah hari ini" advisor={chip}
        info="Belanja hari ini dibanding jatah sejak pagi: dana amplop harian awal hari dibagi sisa hari, dipagari dana harian dibagi jumlah hari periode (uang masuk di tengah periode dibagi rata, kelebihannya jadi surplus). Amplop bulanan tidak dihitung. Garis putih: jatah."
        value={rpFull(k.jatah.spent)}
        suffix={k.jatah.j0 > 0 ? `/ ${rpFull(k.jatah.j0)}` : null}
        alert={advMeter.over}
        bar={{
          fill: advMeter.fill, marker: advMeter.marker,
          color: advMeter.over ? tt.danger.bar : tt.bars.green,
          ariaLabel: `Belanja hari ini ${rpFull(k.jatah.spent)} dari jatah ${rpFull(k.jatah.j0)}`,
        }}
        footer={[
          m.todayCount > 0 ? `${m.todayCount} transaksi hari ini` : 'Belum ada transaksi hari ini',
          k.jatah.ritme != null ? `ritme ${rpCompact(k.jatah.ritme)}/hari` : null,
        ].filter(Boolean).join(' · ')}
      />
    );
  }
  const { meter, todaySpent, safeDaily, todayCount } = m;
  return (
    <KpiTile
      isDark={isDark} label="Jatah hari ini"
      info="Belanja hari ini dibanding batas aman per hari. Garis putih: batas aman."
      value={rpFull(todaySpent)}
      suffix={safeDaily > 0 ? `/ ${rpFull(safeDaily)}` : null}
      badge={meter.over ? { tone: 'danger', text: `Lewat ${rpFull(meter.overBy)}` } : null}
      alert={meter.over}
      bar={{
        fill: meter.fill, marker: meter.marker,
        color: meter.over ? tt.danger.bar : tt.bars.green,
        ariaLabel: `Belanja hari ini ${rpFull(todaySpent)} dari batas aman ${rpFull(safeDaily)}`,
      }}
      footer={todayCount > 0 ? `${todayCount} transaksi hari ini` : 'Belum ada transaksi hari ini'}
    />
  );
}

export function KpiSisaBebas({ m, isDark, chip, prediction, isCurrentPeriod }) {
  const tt = tileTones(isDark);
  if (m.adv) {
    const { k } = m;
    return (
      <KpiTile
        isDark={isDark} label="Sisa bebas" advisor={chip}
        info="Dana amplop harian dikurangi yang sudah terpakai dan tagihan yang belum dibayar. Saldo amplop bulanan (SPP, cicilan, listrik) dicadangkan, tidak dihitung sebagai uang bebas. Batang: hari yang sudah lewat di periode ini."
        value={rpCompact(k.sisa.value)}
        valueColor={k.sisa.value < 0 ? tt.danger.text : null}
        suffix={k.sisa.sisaHari > 0 ? `dana harian, ${k.sisa.sisaHari} hari` : 'dana harian'}
        bar={{ fill: k.sisa.progress, color: tt.bars.slate, ariaLabel: k.sisa.dayLabel }}
        footer={[
          k.sisa.dayLabel,
          k.sisa.j1 != null ? `jaga ${rpCompact(k.sisa.j1)}/hari` : null,
          k.sisa.cadangan > 0 ? `dicadangkan ${rpCompact(k.sisa.cadangan)}` : null,
        ].filter(Boolean).join(' · ')}
      />
    );
  }
  const { sisaBebas, safeDaily } = m;
  return (
    <KpiTile
      isDark={isDark} label="Sisa bebas"
      info="Saldo amplop belanja dikurangi tabungan dan tagihan yang belum dibayar. Batang: hari yang sudah lewat di periode ini."
      value={rpCompact(sisaBebas)}
      valueColor={sisaBebas < 0 ? tt.danger.text : null}
      suffix={isCurrentPeriod ? daysLabel(prediction) : null}
      bar={{ fill: isCurrentPeriod ? periodProgress(prediction) : 1, color: tt.bars.slate, ariaLabel: isCurrentPeriod ? periodDayLabel(prediction) : 'Periode selesai' }}
      footer={isCurrentPeriod && prediction
        ? `${periodDayLabel(prediction)} · aman ${rpCompact(safeDaily)}/hari`
        : null}
    />
  );
}

export function KpiTerpakai({ m, isDark, chip, prediction }) {
  const tt = tileTones(isDark);
  if (m.adv) {
    const { k } = m;
    return (
      <KpiTile
        isDark={isDark} label="Terpakai periode ini" advisor={chip}
        info="Belanja periode ini dari dana amplop belanja (tanpa tabungan). Garis tegak: hari yang sudah lewat; batang kuning = terpakai lebih cepat dari waktu."
        value={rpCompact(k.terpakai.value)}
        suffix="dari dana belanja"
        bar={{
          fill: k.terpakai.fill, split: k.terpakai.waktu, color: tt.bars.green, lateColor: tt.bars.amber,
          ariaLabel: `Terpakai ${rpCompact(k.terpakai.value)} dari ${rpCompact(k.terpakai.dana)}, waktu ${Math.round(k.terpakai.waktu * 100)}%`,
        }}
        footer={[
          k.terpakai.persen != null ? `${k.terpakai.persen}% · waktu ${Math.round(k.terpakai.waktu * 100)}%` : null,
          k.terpakai.proyeksi != null ? `perkiraan akhir ±${rpCompact(k.terpakai.proyeksi)}` : null,
        ].filter(Boolean).join(' · ')}
      />
    );
  }
  const { totalSpent, fundsTotal } = m;
  return (
    <KpiTile
      isDark={isDark} label="Terpakai periode ini"
      info="Belanja periode ini dari dana amplop (alokasi + rollover). Prediksi lewat: perkiraan akhir periode di atas dana itu."
      value={rpCompact(totalSpent)}
      suffix="dari dana amplop"
      badge={predictionOver(prediction) ? { tone: 'warn', text: 'Prediksi lewat' } : null}
      bar={{ fill: fundsTotal > 0 ? totalSpent / fundsTotal : 0, color: tt.bars.green, ariaLabel: `Terpakai ${rpCompact(totalSpent)} dari ${rpCompact(fundsTotal)}` }}
      footer={[
        fundsTotal > 0 ? `${Math.round((totalSpent / fundsTotal) * 100)}%` : null,
        prediction ? `prediksi akhir periode ${rpCompact(prediction.predicted_total)}` : null,
      ].filter(Boolean).join(' · ')}
    />
  );
}

export function KpiIncome({ m, isDark, chip, prediction }) {
  const tt = tileTones(isDark);
  if (m.adv) {
    const { k } = m;
    return (
      <KpiTile
        isDark={isDark} label="Income periode ini" advisor={chip}
        info="Pemasukan rumah tangga periode ini (termasuk yang dicatat anggota lain). Batang: bagian yang kamu catat."
        value={rpCompact(k.income.value)}
        valueColor={k.income.value === 0 ? tt.warn.text : null}
        suffix={k.income.saya !== k.income.value ? `kamu ${rpCompact(k.income.saya)}` : null}
        badge={k.income.value === 0 ? { tone: 'warn', text: 'Belum dicatat' } : null}
        bar={{ fill: k.income.share, color: tt.bars.green, ariaLabel: `Pemasukanmu ${rpCompact(k.income.saya)} dari ${rpCompact(k.income.value)}` }}
        footer={k.income.kekurangan == null ? null
          : k.income.kekurangan > 0 ? `Arus kas kurang ±${rpCompact(k.income.kekurangan)} di akhir periode`
            : 'Arus kas cukup sampai akhir periode'}
      />
    );
  }
  const { income } = m;
  return (
    <KpiTile
      isDark={isDark} label="Income periode ini"
      info="Pemasukan periode ini. Saving rate: uang yang masuk ke amplop tabungan dan sinking fund dibagi pemasukan."
      value={rpCompact(income)}
      valueColor={prediction && income === 0 ? tt.warn.text : null}
      suffix={prediction ? savingRateLabel(prediction) : null}
      badge={prediction && income === 0 ? { tone: 'warn', text: 'Belum dicatat' } : null}
      bar={{ fill: (Number(prediction?.saving_rate) || 0) / 100, color: tt.bars.green, ariaLabel: savingRateLabel(prediction) }}
      footer={cashFlowLabel(prediction)}
    />
  );
}

export function KpiTagihan({ m, isDark, chip, recurringStats }) {
  const tt = tileTones(isDark);
  const { bills } = m;
  return (
    <KpiTile
      isDark={isDark} label="Tagihan belum dibayar" advisor={chip}
      info="Tagihan bulanan yang jatuh tempo periode ini dan belum dibayar. Telat: ada yang lewat tanggal jatuh tempo."
      value={rpCompact(bills.due)}
      valueColor={recurringStats?.has_overdue ? tt.danger.text : null}
      suffix={recurringStats?.count_total ? `${recurringStats.count_due} dari ${recurringStats.count_total} tagihan` : 'tidak ada tagihan'}
      badge={recurringStats?.has_overdue ? { tone: 'danger', text: 'Telat' } : null}
      alert={!!recurringStats?.has_overdue}
      bar={{ fill: bills.fill, color: tt.bars.green, ariaLabel: `Lunas ${rpCompact(bills.paid)} dari ${rpCompact(bills.total)}` }}
      footer={bills.total > 0 ? `Lunas ${rpCompact(bills.paid)} dari ${rpCompact(bills.total)} bulan ini` : null}
    />
  );
}

export function KpiTabungan({ m, isDark, chip, goals, envelopes }) {
  const tt = tileTones(isDark);
  return (
    <KpiTile
      isDark={isDark} label="Tabungan" advisor={chip}
      info="Saldo amplop tabungan dan sinking fund. Batang: kemajuan semua target tabungan."
      value={rpCompact(m.totalSaving)}
      suffix={m.savingGoalCount > 0 ? `${m.savingGoalCount} target` : 'tanpa target'}
      bar={{ fill: savingsProgress(goals, envelopes, null) || 0, color: tt.bars.purple, ariaLabel: 'Kemajuan target tabungan' }}
      footer={`Bersama ${rpCompact(m.sharedSaving)} · Pribadi ${rpCompact(m.personalSaving)}`}
    />
  );
}
