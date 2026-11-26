"use strict";

// `npm start` runs this first. If electron.exe was never unpacked, download it and
// extract it with tar, then write the path file Electron's launcher expects.
// When not pointed at a dev server, also build renderer/dist so main.js has
// index.html, but only when a renderer source is newer than the last build.
// Delete renderer/dist to force a rebuild.

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const electronRoot = path.join(__dirname, "node_modules", "electron");
const dist = path.join(electronRoot, "dist");
const exe = path.join(dist, "electron.exe");
const pathFile = path.join(electronRoot, "path.txt");

// Everything the renderer build reads. The option spec is imported from above the Vite root.
const RENDERER_INPUTS = [
  "renderer/src",
  "renderer/public",
  "renderer/index.html",
  "renderer/vite.config.ts",
  "renderer/tsconfig.json",
  "renderer/package.json",
  "shared/opts-spec.json",
];
const RENDERER_OUTPUT = "renderer/dist/index.html";

// Latest modification time under a file or folder, or 0 when it is missing.
function newestMtime(target) {
  let stat;
  try {
    stat = fs.statSync(target);
  } catch {
    return 0;
  }
  if (!stat.isDirectory()) return stat.mtimeMs;
  let newest = stat.mtimeMs;
  for (const entry of fs.readdirSync(target)) newest = Math.max(newest, newestMtime(path.join(target, entry)));
  return newest;
}

// True when renderer/dist is missing or older than any of its sources.
function needsRendererBuild(root = __dirname) {
  const built = newestMtime(path.join(root, RENDERER_OUTPUT));
  if (!built) return true;
  return RENDERER_INPUTS.some((input) => newestMtime(path.join(root, input)) > built);
}

async function main() {
  if (!fs.existsSync(exe) || !fs.existsSync(pathFile)) {
    const { downloadArtifact } = require("@electron/get");
    const version = require(path.join(electronRoot, "package.json")).version;
    const zip = await downloadArtifact({
      version,
      artifactName: "electron",
      platform: "win32",
      arch: process.arch,
      checksums: require(path.join(electronRoot, "checksums.json")),
    });
    fs.mkdirSync(dist, { recursive: true });
    // ponytail: tar, not extract-zip. Node 24 drops yauzl's handle, so electron's postinstall exits before path.txt exists.
    const unpacked = spawnSync("tar", ["-xf", zip, "-C", dist], { stdio: "inherit" });
    if (unpacked.status !== 0) process.exit(unpacked.status || 1);
    fs.writeFileSync(pathFile, "electron.exe");
    if (!fs.existsSync(exe)) {
      console.error("electron.exe missing after unpack");
      process.exit(1);
    }
  }

  if (!process.env.VITE_DEV_SERVER_URL && needsRendererBuild()) {
    const built = spawnSync("npm --prefix renderer run build", {
      cwd: __dirname,
      stdio: "inherit",
      shell: true,
    });
    if (built.status !== 0) process.exit(built.status || 1);
  }
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}

module.exports = { needsRendererBuild };
