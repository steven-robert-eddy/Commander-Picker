import { useState } from "react";
import type { FavoriteStatus } from "@commander-hq/shared";
import { api } from "../api/client";

const FAV_CYCLE: Record<string, FavoriteStatus | "none"> = { none: "owned", owned: "wishlist", wishlist: "none" };
const FAV_LABELS: Record<string, string> = { none: "+ Fav", owned: "Owned", wishlist: "Wishlist" };

/**
 * Owned/wishlist collection toggle -- cycles none -> owned -> wishlist ->
 * none, optimistic with revert-on-failure. Hidden via CSS (`.fav-btn {
 * display: none }`) after user feedback, same as the Python app -- kept
 * fully wired so it's a one-line CSS change to bring back.
 */
export function FavButton({
  commanderName,
  status,
  onStatusChange,
}: {
  commanderName: string;
  status: FavoriteStatus | null | undefined;
  onStatusChange?: (status: FavoriteStatus | null) => void;
}) {
  const [current, setCurrent] = useState<FavoriteStatus | "none">(status ?? "none");

  const handleClick = async (e: React.MouseEvent) => {
    e.stopPropagation(); // rank rows with art also open the lightbox on click
    const previous = current;
    const next = FAV_CYCLE[current];
    setCurrent(next);
    onStatusChange?.(next === "none" ? null : next);
    try {
      if (next === "none") {
        await api.clearFavorite(commanderName);
      } else {
        await api.setFavorite(commanderName, next);
      }
    } catch {
      setCurrent(previous);
      onStatusChange?.(previous === "none" ? null : previous);
    }
  };

  return (
    <button className="fav-btn" type="button" data-status={current} aria-pressed={current !== "none"} onClick={handleClick}>
      {FAV_LABELS[current]}
    </button>
  );
}
