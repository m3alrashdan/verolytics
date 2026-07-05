"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Lang = "en" | "ar";
export interface AuthUser { id: string; email: string }

interface UIState {
  theme: "light" | "dark";
  lang: Lang;
  confetti: boolean;
  onboarded: boolean;
  token: string | null;
  user: AuthUser | null;
  toggleTheme: () => void;
  setLang: (l: Lang) => void;
  setConfetti: (v: boolean) => void;
  setOnboarded: () => void;
  setAuth: (token: string, user: AuthUser) => void;
  logout: () => void;
}

export const useUI = create<UIState>()(
  persist(
    (set) => ({
      theme: "dark",
      lang: "en",
      confetti: true,
      onboarded: false,
      token: null,
      user: null,
      toggleTheme: () => set((s) => ({ theme: s.theme === "light" ? "dark" : "light" })),
      setLang: (lang) => set({ lang }),
      setConfetti: (confetti) => set({ confetti }),
      setOnboarded: () => set({ onboarded: true }),
      setAuth: (token, user) => set({ token, user }),
      logout: () => set({ token: null, user: null }),
    }),
    { name: "daa-ui" }
  )
);
