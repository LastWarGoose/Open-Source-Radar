"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

const ToastContext = createContext<(message: string) => void>(() => {});
export const useToast = () => useContext(ToastContext);

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [notice, setNotice] = useState<{ message: string; id: number } | null>(null);
  const notify = useCallback((message: string) => {
    setNotice((previous) => ({ message, id: (previous?.id ?? 0) + 1 }));
  }, []);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 3200);
    return () => window.clearTimeout(timer);
  }, [notice]);
  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div className="toast-region" role="status" aria-live="polite" aria-atomic="true">
        {notice && (
          <div key={notice.id} className="toast">
            {notice.message}
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}
