#!/usr/bin/env node
import { Command } from "commander";
import { colors, themes } from "@commander-hq/shared";
import { createApp } from "./app.js";
import * as edhrec from "./clients/edhrec.js";
import * as scryfall from "./clients/scryfall.js";
import * as catalog from "./db/catalog.js";
import * as sessionsDb from "./db/sessions.js";
import * as pool from "./domain/pool.js";
import * as sessionsDomain from "./domain/sessions.js";

const program = new Command();
program.name("commander-hq");

function splitCsv(value: string | undefined): string[] | undefined {
  return value ? value.split(",") : undefined;
}

program
  .command("update-data")
  .description("fetch EDHREC pages and rebuild the local DB")
  .option("--force", "bypass the freshness cache", false)
  .option("--colors <slugs>", "comma-separated color slugs to fetch (default: all)")
  .option("--themes <slugs>", "comma-separated theme slugs to fetch (default: all)")
  .option("--sets <slugs>", "comma-separated EDHREC set slugs to fetch (default: whatever's already cached)")
  .option("--discover-sets", "crawl Scryfall's set-code index for every set with an EDHREC set page", false)
  .option("--skip-images", "skip fetching Scryfall card details (images, mana cost, type line, price)", false)
  .action(async (opts) => {
    let colorSlugs = splitCsv(opts.colors);
    let themeSlugs = splitCsv(opts.themes);
    let setSlugs = splitCsv(opts.sets);

    if (opts.discoverSets) {
      console.log("Discovering EDHREC set pages (this can take a while)...");
      const discovered = await edhrec.discoverSetSlugs(opts.force);
      console.log(`  found ${discovered.length} set page(s) on EDHREC`);
      setSlugs = [...new Set([...(setSlugs ?? []), ...discovered])].sort();
    }

    console.log("Fetching EDHREC pages...");
    const [results, failures] = await edhrec.fetchAllPages({
      force: opts.force,
      colorSlugs,
      themeSlugs,
      setSlugs,
    });
    const fetched = results.filter((r) => !r.fromCache).length;
    const cached = results.length - fetched;
    console.log(`  ${fetched} fetched, ${cached} served from cache (${results.length} pages total)`);
    if (failures.length > 0) {
      const colorFailures = failures.filter((f) => f.kind === "color");
      const themeFailures = failures.filter((f) => f.kind === "theme");
      const setFailures = failures.filter((f) => f.kind === "set");
      if (colorFailures.length > 0) {
        console.error(`  warning: ${colorFailures.length} color page(s) failed:`);
        for (const f of colorFailures) console.error(`    ${f.slug}: ${f.error}`);
      }
      if (themeFailures.length > 0) {
        console.log(`  note: ${themeFailures.length} theme slug(s) skipped (not found on EDHREC): ${themeFailures.map((f) => f.slug).join(", ")}`);
      }
      if (setFailures.length > 0) {
        console.log(`  note: ${setFailures.length} set slug(s) skipped (not found on EDHREC): ${setFailures.map((f) => f.slug).join(", ")}`);
      }
    }

    let imageLookup: Map<string, string[]> | undefined;
    let cardMetaLookup: Map<string, scryfall.CardMeta> | undefined;
    if (!opts.skipImages) {
      console.log("Fetching Scryfall card details...");
      try {
        const oraclePath = await scryfall.fetchOracleCards(opts.force);
        imageLookup = scryfall.buildImageLookup(oraclePath);
        cardMetaLookup = scryfall.buildCardMetaLookup(oraclePath);
        console.log(`  ${imageLookup.size} card images, ${cardMetaLookup.size} card details available`);
      } catch (exc) {
        console.error(`  warning: couldn't fetch card details (${(exc as Error).message}) -- continuing without them`);
      }
    }

    console.log("Building data/commanders.db...");
    try {
      const dbPath = catalog.buildDatabase({ colorSlugs, themeSlugs, setSlugs, imageLookup, cardMetaLookup });
      console.log(`  wrote ${dbPath}`);
    } catch (exc) {
      if (exc instanceof catalog.DbError) {
        console.error(`error: ${exc.message}`);
        process.exitCode = 1;
        return;
      }
      throw exc;
    }
  });

program
  .command("enrich-commanders")
  .description("fetch+cache each commander's own EDHREC detail page (salt score, richer tags)")
  .option("--limit <n>", "stop after this many NEW fetches (default: unbounded)", (v) => parseInt(v, 10))
  .option("--force", "bypass the freshness cache", false)
  .action(async (opts) => {
    let db;
    try {
      db = catalog.connect();
    } catch (exc) {
      console.error(`error: ${(exc as Error).message}`);
      process.exitCode = 1;
      return;
    }
    let rows: { name: string; sanitized: string }[];
    try {
      rows = db.prepare("SELECT name, sanitized FROM commanders ORDER BY name").all() as { name: string; sanitized: string }[];
    } finally {
      db.close();
    }

    let fetched = 0;
    let skipped = 0;
    let failed = 0;
    for (const { name, sanitized } of rows) {
      if (!sanitized) continue;
      if (!opts.force && edhrec.pageExists("commander", sanitized)) {
        skipped++;
        continue;
      }
      if (opts.limit !== undefined && fetched >= opts.limit) break;
      try {
        await edhrec.fetchCommanderDetailPage(sanitized, opts.force);
      } catch (exc) {
        console.error(`  warning: ${name} (${sanitized}): ${(exc as Error).message}`);
        failed++;
        continue;
      }
      fetched++;
      if (fetched % 50 === 0) console.log(`  ...${fetched} fetched so far`);
      await new Promise((r) => setTimeout(r, edhrec.REQUEST_DELAY_SECONDS * 1000));
    }

    console.log(`Done: ${fetched} fetched, ${skipped} already cached, ${failed} failed.`);
    if (fetched) console.log("Run `update-data` to fold the newly cached detail pages into commanders.db.");
  });

program
  .command("refresh-candidates")
  .description("resync candidates' denormalized color/deck-count/art from the current commanders.db")
  .action(() => {
    let catalogConn;
    try {
      catalogConn = catalog.connect();
    } catch (exc) {
      console.error(`error: ${(exc as Error).message}`);
      process.exitCode = 1;
      return;
    }
    const sessionsConn = sessionsDb.connect();
    try {
      const result = sessionsDomain.refreshCandidateMetadata(sessionsConn, catalogConn);
      console.log(`Done: ${result.updated} commander(s) refreshed, ${result.notFound} not found in the current catalog.`);
    } finally {
      sessionsConn.close();
      catalogConn.close();
    }
  });

program
  .command("list-colors")
  .description("print all known color-identity slugs")
  .action(() => {
    for (const slug of colors.allSlugs()) console.log(slug);
  });

program
  .command("list-themes")
  .description("print all known theme slugs")
  .action(() => {
    for (const slug of themes.THEME_SLUGS) console.log(slug);
  });

program
  .command("list-sets")
  .description("print all known set slugs (from the current commanders.db)")
  .action(() => {
    let db;
    try {
      db = catalog.connect();
    } catch (exc) {
      console.error(`error: ${(exc as Error).message}`);
      process.exitCode = 1;
      return;
    }
    try {
      for (const entry of pool.listKnownSets(db)) console.log(`${entry.slug}\t${entry.name}`);
    } finally {
      db.close();
    }
  });

program
  .command("serve")
  .description("run the web UI (Express API + built React frontend)")
  .option("--host <host>", "host to bind", "127.0.0.1")
  .option("--port <port>", "port to bind", (v) => parseInt(v, 10), 8000)
  .action((opts) => {
    try {
      catalog.connect().close();
    } catch (exc) {
      console.error(`error: ${(exc as Error).message}`);
      process.exitCode = 1;
      return;
    }
    const app = createApp();
    app.listen(opts.port, opts.host, () => {
      console.log(`Commander HQ listening on http://${opts.host}:${opts.port}`);
    });
  });

program.parseAsync(process.argv);
