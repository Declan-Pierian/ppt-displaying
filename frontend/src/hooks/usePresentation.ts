import { useState, useEffect, useCallback } from "react";
import api from "../lib/api";
import type { PresentationMeta } from "../types/slide";

export function usePresentationList() {
  const [presentations, setPresentations] = useState<PresentationMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/presentations");
      setPresentations(res.data);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load presentations");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { presentations, loading, error, refresh };
}
