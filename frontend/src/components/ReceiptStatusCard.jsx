import { STAGE, stageLabel, stageSteps } from '../lib/receiptProgress';
import { useTicker } from '../hooks/useTicker';
import { Icon } from './Icon';

const BUSY_STAGES = [STAGE.PREPARING, STAGE.UPLOADING, STAGE.READING];

function StepRow({ step }) {
  const tone = step.state === 'done' ? 'text-brand-600' : step.state === 'active' ? 'text-gray-700 font-medium' : 'text-gray-400';
  return (
    <li className={`flex items-center gap-1.5 text-xs ${tone}`}>
      <span className="w-4 h-4 flex items-center justify-center shrink-0" aria-hidden="true">
        {step.state === 'done' && <Icon name="check" size={14} />}
        {step.state === 'active' && <Icon name="spinner" size={14} className="animate-spin" />}
        {step.state === 'todo' && <span className="w-1.5 h-1.5 rounded-full bg-gray-300" />}
      </span>
      {step.label}
    </li>
  );
}

// Kartu tahap proses baca struk (di bawah kotak teks). Tidak menampilkan apa pun saat idle.
// onRetry(): kirim ulang foto yang sama · onRetake(): ambil foto baru (harus memanggil kamera langsung dari onClick).
// onDismiss(): tutup kartu gagal (tombol Tutup; hanya tampil bila diberikan).
// disabled: tombol Coba lagi / Foto ulang dimatikan (mis. induk sedang menyimpan).
//
// Pembaca layar: wadah role="status" selalu terpasang dan awalnya kosong (live region yang sudah
// terisi saat dipasang sering tidak dibacakan). Isinya hanya nama tahap atau teks gagal, jadi
// persen yang berubah tiap saat tidak diumumkan; judul berpersen ada di luar wadah itu.
export default function ReceiptStatusCard({ state, onRetry, onRetake, onDismiss, disabled = false }) {
  const busy = BUSY_STAGES.includes(state.stage);
  const now = useTicker(busy);

  const failed = state.stage === STAGE.FAILED;
  const failure = state.failure;
  const activeStep = stageSteps(state.stage).find(s => s.state === 'active');
  const announce = failed ? failure?.text : activeStep?.label;
  const { title, hint } = stageLabel({
    stage: state.stage,
    percent: state.percent,
    progressSeen: state.progressSeen,
    elapsedMs: Math.max(0, now - state.stageStartedAt),
  });

  const card = state.stage === STAGE.IDLE ? null : (
    <div className="mt-2 flex items-start gap-3 rounded-xl border border-gray-100 bg-gray-50 p-2.5">
      {state.thumbUrl && (
        <img
          src={state.thumbUrl}
          alt="Foto struk"
          className="w-14 h-14 rounded-lg object-cover shrink-0 border border-gray-100"
        />
      )}
      <div className="min-w-0 flex-1">
        {failed ? (
          <>
            <p className="text-sm text-red-500 font-medium">{failure?.text}</p>
            {(failure?.canRetry || failure?.canRetake || onDismiss) && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {failure?.canRetry && (
                  <button
                    type="button"
                    onClick={onRetry}
                    disabled={disabled}
                    className="inline-flex items-center gap-1.5 bg-brand-600 hover:bg-brand-700 text-white rounded-lg px-2.5 py-1.5 text-xs font-medium transition-all disabled:opacity-50"
                  >
                    <Icon name="retry" size={13} /> Coba lagi
                  </button>
                )}
                {failure?.canRetake && (
                  <button
                    type="button"
                    onClick={onRetake}
                    disabled={disabled}
                    className="inline-flex items-center gap-1.5 border border-brand-200 text-brand-600 hover:bg-brand-50 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-all disabled:opacity-50"
                  >
                    <Icon name="camera" size={13} /> Foto ulang
                  </button>
                )}
                {onDismiss && (
                  <button
                    type="button"
                    onClick={onDismiss}
                    className="rounded-lg px-2 py-1.5 text-xs font-medium text-gray-500 hover:text-gray-700 hover:underline underline-offset-2 transition-colors"
                  >
                    Tutup
                  </button>
                )}
              </div>
            )}
          </>
        ) : (
          <>
            <p className="text-sm text-gray-700 font-medium">{title}</p>
            {hint && <p className="text-xs text-gray-400 mt-0.5">{hint}</p>}
            <ul className="mt-1.5 space-y-0.5">
              {stageSteps(state.stage).map(step => <StepRow key={step.key} step={step} />)}
            </ul>
          </>
        )}
      </div>
    </div>
  );

  // Wadah status tetap anak pertama fragment di semua tahap: kalau posisinya berpindah, React
  // memasangnya ulang dan pembaca layar melewatkan isinya.
  return (
    <>
      <div role="status" aria-live="polite" className="sr-only">
        {announce && <span>{announce}</span>}
      </div>
      {card}
    </>
  );
}
