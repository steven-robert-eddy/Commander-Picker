import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { FavoriteStatus } from "@commander-hq/shared";
import { FavButton } from "./FavButton";

interface LightboxState {
  imageUrls: string[];
  name: string;
  edhrecUrl: string | null;
  favoriteStatus: FavoriteStatus | null;
  onFavoriteChange?: (status: FavoriteStatus | null) => void;
}

interface LightboxContextValue {
  open: (state: LightboxState) => void;
}

const LightboxContext = createContext<LightboxContextValue | null>(null);

export function useLightbox(): LightboxContextValue {
  const ctx = useContext(LightboxContext);
  if (!ctx) throw new Error("useLightbox must be used within LightboxProvider");
  return ctx;
}

export function LightboxProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<LightboxState | null>(null);

  const open = useCallback((s: LightboxState) => {
    if (s.imageUrls.length === 0) return;
    setState(s);
  }, []);
  const close = useCallback(() => setState(null), []);

  const value = useMemo(() => ({ open }), [open]);

  useEffect(() => {
    if (!state) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [state, close]);

  const query = state?.name ? encodeURIComponent(state.name) : "";

  return (
    <LightboxContext.Provider value={value}>
      {children}
      <div
        className={`lightbox ${state ? "" : "hidden"}`}
        role="dialog"
        aria-modal="true"
        aria-label="Card view"
        onClick={(e) => {
          if (e.target === e.currentTarget) close();
        }}
      >
        <button className="lightbox-close" aria-label="Close" onClick={close}>
          ✕
        </button>
        <div className="lightbox-name">{state?.name ?? ""}</div>
        <div className="lightbox-images">
          {state?.imageUrls.map((url, i) => (
            <img key={i} src={url} alt={state.name} />
          ))}
        </div>
        <div className="lightbox-links">
          {state?.edhrecUrl && (
            <a href={state.edhrecUrl} target="_blank" rel="noopener noreferrer">
              View on EDHREC →
            </a>
          )}
          {state?.name && (
            <>
              <a href={`https://www.moxfield.com/decks?q=${query}`} target="_blank" rel="noopener noreferrer">
                Search Moxfield
              </a>
              <a href={`https://archidekt.com/search/decks?q=${query}`} target="_blank" rel="noopener noreferrer">
                Search Archidekt
              </a>
              <FavButton commanderName={state.name} status={state.favoriteStatus} onStatusChange={state.onFavoriteChange} />
            </>
          )}
        </div>
      </div>
    </LightboxContext.Provider>
  );
}
