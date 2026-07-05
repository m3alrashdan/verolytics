"use client";
import { AnimatePresence, motion } from "framer-motion";
import { BarChart3, Lightbulb, UploadCloud } from "lucide-react";
import { useState } from "react";
import { t } from "@/lib/i18n";
import { useUI } from "@/lib/store";

const ICONS = [UploadCloud, BarChart3, Lightbulb];

export default function Onboarding() {
  const { lang, onboarded, setOnboarded } = useUI();
  const tr = t(lang);
  const [step, setStep] = useState(0);
  if (onboarded) return null;
  const Icon = ICONS[step];
  const last = step === tr.onboarding.length - 1;

  return (
    <AnimatePresence>
      <motion.div className="fixed inset-0 z-[80] grid place-items-center bg-black/40 p-4 backdrop-blur-sm"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
        <motion.div layout className="card-raised w-full max-w-md p-8 text-center"
          initial={{ scale: 0.92, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
          <motion.div key={step} initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
            className="mx-auto mb-4 grid h-16 w-16 place-items-center rounded-2xl bg-grad-iris text-white shadow-glow">
            <Icon size={30} />
          </motion.div>
          <h2 className="font-heading text-xl font-bold">{tr.onboarding[step].title}</h2>
          <p className="mt-2 text-sm text-muted">{tr.onboarding[step].body}</p>
          <div className="mt-5 flex justify-center gap-1.5">
            {tr.onboarding.map((_, i) => (
              <span key={i} className={`h-1.5 rounded-full transition-all ${
                i === step ? "w-6 bg-grad-brand" : "w-1.5 bg-line-strong"}`} />
            ))}
          </div>
          <button
            onClick={() => (last ? setOnboarded() : setStep(step + 1))}
            className="btn-grad mt-6 w-full rounded-xl py-3 font-semibold">
            {last ? tr.skip : tr.next}
          </button>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
