import fs from "node:fs";
import path from "node:path";
import express, { NextFunction, Request, Response } from "express";
import { ZodError } from "zod";
import { catalogRouter } from "./routes/catalog.js";
import { challengeRouter } from "./routes/challenge.js";
import { favoritesRouter } from "./routes/favorites.js";
import { leaderboardRouter } from "./routes/leaderboard.js";
import { podRouter } from "./routes/pod.js";
import { poolRouter } from "./routes/pool.js";
import { sessionsRouter } from "./routes/sessions.js";
import { setChallengeRouter } from "./routes/setChallenge.js";
import { HttpError } from "./requestDb.js";
import { WEB_DIST_DIR } from "./paths.js";

export function createApp() {
  const app = express();
  app.use(express.json());

  const api = express.Router();
  api.use(catalogRouter);
  api.use(poolRouter);
  api.use(sessionsRouter);
  api.use(leaderboardRouter);
  api.use(challengeRouter);
  api.use(setChallengeRouter);
  api.use(favoritesRouter);
  api.use(podRouter);
  app.use("/api", api);

  if (fs.existsSync(WEB_DIST_DIR)) {
    app.use(express.static(WEB_DIST_DIR));
    app.get(/^(?!\/api).*/, (_req, res) => {
      res.sendFile(path.join(WEB_DIST_DIR, "index.html"));
    });
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
    if (err instanceof HttpError) {
      res.status(err.status).json({ error: err.message });
      return;
    }
    if (err instanceof ZodError) {
      res.status(422).json({ error: err.message });
      return;
    }
    console.error(err);
    res.status(500).json({ error: "Internal server error" });
  });

  return app;
}
