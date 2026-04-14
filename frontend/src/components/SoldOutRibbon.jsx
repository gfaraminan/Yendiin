export default function SoldOutRibbon({ className = "" }) {
  return (
    <div className={`pointer-events-none absolute inset-x-0 top-4 z-20 ${className}`}>
      <div className="w-full py-2.5 bg-gradient-to-r from-rose-600/95 via-red-500/95 to-rose-600/95 border-y border-rose-200/70 shadow-[0_10px_28px_rgba(244,63,94,0.45)]">
        <div className="text-center">
          <span className="text-[12px] font-black uppercase tracking-[0.32em] text-white">SOLD OUT</span>
        </div>
      </div>
    </div>
  );
}
