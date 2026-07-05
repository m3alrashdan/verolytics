/** Verolytics mark (dc2) — aurora gradient rounded square with a ringed dot. */
export default function Logo({ size = 30 }: { size?: number }) {
  const dot = Math.round(size * 0.37);
  return (
    <span
      className="relative grid place-items-center bg-grad-brand"
      style={{
        width: size,
        height: size,
        borderRadius: size * 0.3,
        boxShadow: "0 6px 18px -6px var(--glow-violet)",
      }}
    >
      <span
        style={{
          width: dot,
          height: dot,
          borderRadius: "50%",
          background: "var(--bg-1)",
          boxShadow: "0 0 0 2.5px rgba(255,255,255,0.9) inset",
        }}
      />
    </span>
  );
}
