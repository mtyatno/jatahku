// Grid Beranda (Plugin B2): instans dari tata letak disusun baris demi baris (lib/dashboardRegistry.js
// packRows), setiap baris berupa grid sendiri dengan kolom sesuai ukuran kartu. Breakpoint dibaca dari
// lebar layar supaya kartu terakhir di baris bisa melebar; urutan DOM = urutan tata letak = urutan baca.
import { useEffect, useState } from 'react';
import { breakpointOf, groupsOf, packRows, rowGapAbove, rowKind, visibleItems } from '../lib/dashboardRegistry';
import { getCard, knownCard } from './CardRegistry';
import CardFrame from './CardFrame';

export function useBreakpoint() {
  const lebar = () => (typeof window === 'undefined' ? 1280 : window.innerWidth);
  const [bp, setBp] = useState(() => breakpointOf(lebar()));
  useEffect(() => {
    const onResize = () => setBp(breakpointOf(lebar()));
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return bp;
}

export default function DashboardGrid({ layout, data, ctx, judul }) {
  const bp = useBreakpoint();
  // Kartu yang datanya sudah ada tapi tidak relevan sekarang (kosong) dibuang sebelum disusun.
  const items = visibleItems(layout, bp, knownCard).filter(i => {
    const entri = data?.[i.id];
    return entri === undefined || entri?.error || !getCard(i.card).kosong(entri, ctx);
  });
  const opts = { ownRow: (i) => getCard(i.card).ownRow };
  const rows = packRows(items, bp, opts);
  const groups = groupsOf(items, opts);

  let prevKind = null;
  let prevGroup = null;
  return (
    <div className="lg:!mt-0">
      {rows.map((row) => {
        const defs = row.cells.map(c => getCard(c.item.card));
        const kind = rowKind(defs.map(d => d.kind));
        const group = groups[row.cells[0].item.id];
        const marginTop = rowGapAbove(prevKind, kind, group === prevGroup);
        prevKind = kind;
        prevGroup = group;
        return (
          <div key={row.cells.map(c => c.item.id).join('|')}
            className={`grid ${kind === 'kpi' ? 'gap-3' : 'gap-4'} ${defs.some(d => d.alignStart) ? 'items-start' : ''}`}
            style={{ gridTemplateColumns: row.template, marginTop }}>
            {row.cells.map(({ item }, i) => {
              const def = defs[i];
              const Card = def.Component;
              return (
                <CardFrame key={item.id} def={def} entri={data?.[item.id]} judul={judul?.[item.card]}>
                  <Card entri={data?.[item.id]} item={item} ctx={ctx} />
                </CardFrame>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
