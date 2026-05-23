import { app } from "electron";
import log from "electron-log";
import fs from "fs";
import path from "path";

// ─────────────────────────────────────────────────────────────────────────────
// Logger Setup
// Outputs structured JSON to daily rotating log files.
// Console output is human-readable in development.
// Privacy rule: NEVER log metadata values (supplier names, item numbers etc.)
// ─────────────────────────────────────────────────────────────────────────────

const LOG_RETENTION_DAYS = 30;

function getLogDir(): string {
  const dir = path.join(app.getPath("userData"), "logs");
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function todayFileName(): string {
  return `app-${new Date().toISOString().slice(0, 10)}.log`;
}

export function setupLogger(): void {
  const logDir = getLogDir();

  // ── File transport: one file per day, JSON format ─────────────────────────
  log.transports.file.resolvePathFn = () => path.join(logDir, todayFileName());
  log.transports.file.level = "info";
  log.transports.file.format = (msg) => {
    const entry = {
      ts: msg.date.toISOString(),
      level: msg.level.toUpperCase(),
      component: "electron",
      msg: msg.data
        .map((d: unknown) =>
          typeof d === "object" ? JSON.stringify(d) : String(d),
        )
        .join(" "),
    };
    return JSON.stringify(entry);
  };

  // ── Console transport: readable in dev ────────────────────────────────────
  log.transports.console.level =
    process.env.NODE_ENV === "development" ? "debug" : "warn";
  log.transports.console.format = "[{level}] {component} › {text}";

  // ── Prune logs older than 30 days ─────────────────────────────────────────
  pruneOldLogs(logDir);

  // ── Capture unhandled exceptions ──────────────────────────────────────────
  log.catchErrors({
    showDialog: false,
    onError: (error) => {
      logCritical("Unhandled exception", {
        error: error.message,
        stack: error.stack,
      });
    },
  });

  logInfo("Logger initialised", {
    logDir,
    retention: `${LOG_RETENTION_DAYS}d`,
  });
}

function pruneOldLogs(logDir: string): void {
  try {
    const cutoff = Date.now() - LOG_RETENTION_DAYS * 24 * 60 * 60 * 1000;
    const files = fs
      .readdirSync(logDir)
      .filter((f) => f.startsWith("app-") && f.endsWith(".log"));
    let pruned = 0;
    for (const file of files) {
      const filePath = path.join(logDir, file);
      const stat = fs.statSync(filePath);
      if (stat.mtimeMs < cutoff) {
        fs.unlinkSync(filePath);
        pruned++;
      }
    }
    if (pruned > 0) logInfo(`Pruned ${pruned} old log files`);
  } catch (err) {
    // Non-fatal — log rotation failure should not crash the app
    console.error("Failed to prune old logs:", err);
  }
}

// ── Typed log helpers ─────────────────────────────────────────────────────────

type LogMeta = Record<string, unknown>;

export function logDebug(msg: string, meta?: LogMeta): void {
  log.debug(meta ? `${msg} ${JSON.stringify(meta)}` : msg);
}

export function logInfo(msg: string, meta?: LogMeta): void {
  log.info(meta ? `${msg} ${JSON.stringify(meta)}` : msg);
}

export function logWarn(msg: string, meta?: LogMeta): void {
  log.warn(meta ? `${msg} ${JSON.stringify(meta)}` : msg);
}

export function logError(msg: string, meta?: LogMeta): void {
  log.error(meta ? `${msg} ${JSON.stringify(meta)}` : msg);
}

export function logCritical(msg: string, meta?: LogMeta): void {
  log.error(`[CRITICAL] ${msg} ${meta ? JSON.stringify(meta) : ""}`);
}

// export function getLogDir(): string {
//   return path.join(app.getPath('userData'), 'logs')
// }
