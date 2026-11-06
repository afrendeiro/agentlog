// agentlog: record opencode sessions in the agent session log.
// Written to ~/.config/opencode/plugins/ by `agentlog install`, which fills in AGENTLOG.
//
// opencode V2 plugin API (opencode >= 2.x): default export { id, setup }, events via
// `ctx.event.subscribe({ types, signal })` (async iterable of { type, data: { sessionID, ... } }).
//
// opencode has no "session ended" event (it runs as a background service), so:
// - whenever a run finishes (session.execution.succeeded|failed|interrupted), record session
//   metadata (cheap, no LLM call);
// - after SUMMARY_DELAY_MS without further activity, write the summary.

import { spawn } from "node:child_process";
import { homedir } from "node:os";

// Command that runs agentlog, e.g. ["/path/to/python", "-m", "agentlog.cli"].
const AGENTLOG = ["agentlog"]; // @AGENTLOG@
const SUMMARY_DELAY_MS = 20 * 60 * 1000;

const DONE = ["session.execution.succeeded", "session.execution.failed", "session.execution.interrupted"];
const TYPES = [...DONE, "session.execution.started", "session.deleted"];

function sync(sessionID, ...extra) {
  if (process.env.AGENTLOG_SUMMARIZING) return;
  const args = [...AGENTLOG.slice(1), "sync", "--harness", "opencode", "--session", sessionID, ...extra];
  const child = spawn(AGENTLOG[0], args, { cwd: homedir(), detached: true, stdio: "ignore" });
  child.on("error", () => {});
  child.unref();
}

export default {
  id: "agentlog",
  setup: async (ctx) => {
    const timers = new Map();
    const isChild = new Map(); // sessionID -> bool; subagent sessions are folded into their root by sync
    const abort = new AbortController();

    const cancel = (sessionID) => {
      clearTimeout(timers.get(sessionID));
      timers.delete(sessionID);
    };

    const child = async (sessionID) => {
      if (!isChild.has(sessionID)) {
        try {
          const info = await ctx.session.get({ sessionID });
          isChild.set(sessionID, Boolean(info?.parentID));
        } catch {
          return false; // unknown: let sync resolve it to its root
        }
      }
      return isChild.get(sessionID);
    };

    const handle = async (event) => {
      const sessionID = event?.data?.sessionID;
      if (!sessionID) return;
      if (event.type === "session.deleted") {
        cancel(sessionID);
        isChild.delete(sessionID);
        return;
      }
      if (await child(sessionID)) return;
      cancel(sessionID); // execution.started: activity resumed, drop the pending summary
      if (!DONE.includes(event.type)) return;
      if (event.type === "session.execution.interrupted" && event.data.reason === "shutdown") return;
      sync(sessionID, "--no-summary");
      timers.set(sessionID, setTimeout(() => {
        timers.delete(sessionID);
        sync(sessionID);
      }, SUMMARY_DELAY_MS));
    };

    (async () => {
      for await (const event of ctx.event.subscribe({ types: TYPES, signal: abort.signal })) {
        await handle(event).catch(() => {});
      }
    })().catch(() => {});

    return () => {
      abort.abort();
      for (const t of timers.values()) clearTimeout(t);
      timers.clear();
    };
  },
};
