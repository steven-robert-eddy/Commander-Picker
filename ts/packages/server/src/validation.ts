import { z } from "zod";
import { DEFAULT_MAX_DECKS, DEFAULT_MAX_POOL_SIZE, DEFAULT_MIN_DECKS, DEFAULT_MIN_POOL_SIZE } from "@commander-hq/shared";

export const filtersBodySchema = z.object({
  colors: z.string().nullish(),
  colorMode: z.enum(["subset", "exact"]).default("subset"),
  maxDecks: z.number().int().nullish().default(DEFAULT_MAX_DECKS),
  minDecks: z.number().int().nullish().default(DEFAULT_MIN_DECKS),
  themes: z.array(z.string()).default([]),
  themesMode: z.enum(["any", "all"]).default("any"),
  sets: z.array(z.string()).default([]),
  poolSize: z.number().int().min(2).max(200).default(DEFAULT_MAX_POOL_SIZE),
  minPoolSize: z.number().int().min(1).max(200).default(DEFAULT_MIN_POOL_SIZE),
  mode: z.enum(["duel", "bracket"]).default("duel"),
  maxPrice: z.number().nullish(),
  maxSalt: z.number().nullish(),
  minSalt: z.number().nullish(),
});
export type FiltersBodyInput = z.infer<typeof filtersBodySchema>;

export const customSessionBodySchema = z.object({
  names: z.array(z.string()),
  mode: z.enum(["duel", "bracket"]).default("duel"),
});

export const pickBodySchema = z.object({
  winner: z.string(),
  loser: z.string(),
});

export const challengeStatusBodySchema = z.object({
  status: z.string(),
  notes: z.string().nullish(),
});

export const challengeCommanderBodySchema = z.object({
  commanderName: z.string(),
});

export const challengeAddByColorBodySchema = z.object({
  commanderName: z.string(),
  colorIdentity: z.string(),
});

export const favoriteStatusBodySchema = z.object({
  commanderName: z.string(),
  status: z.string(),
});

export const registerDeckBodySchema = z.object({
  name: z.string(),
  commanderName: z.string().nullish(),
  colorIdentity: z.string().nullish(),
  ownerName: z.string().nullish(),
});

export const podParticipantBodySchema = z.object({
  playerName: z.string(),
  deckId: z.string(),
  isWinner: z.boolean().default(false),
});

export const logPodGameBodySchema = z.object({
  participants: z.array(podParticipantBodySchema),
  notes: z.string().default(""),
});
