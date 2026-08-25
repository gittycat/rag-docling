/**
 * Assembles the small set of repo files the instance needs at runtime into a
 * directory under cdk.out, which is then uploaded as a single S3 asset.
 *
 * The instance needs real files, not just images: compose bind-mounts config.yml
 * and the three postgres init scripts. Copying an explicit list keeps the asset at
 * a few hundred KB instead of shipping the whole repo.
 */
import * as fs from 'fs';
import * as path from 'path';

const FILES = [
  'docker-compose.yml',
  'docker-compose.aws.yml',
  'docker-compose.bake.yml',
  'config.yml',
  'services/postgres/00-roles.sh',
  'services/postgres/init.sql',
  'services/postgres/02-grants.sh',
];

const DIRS = ['sample_documents'];

/**
 * Walks up from this module until it finds the repo root. Resolved by marker
 * rather than by a fixed `../..` so it holds whether the app runs from source
 * (tsx) or from a compiled output directory.
 */
export function repoRoot(): string {
  let dir = __dirname;
  for (let i = 0; i < 8; i++) {
    if (fs.existsSync(path.join(dir, 'docker-compose.yml'))) return dir;
    dir = path.dirname(dir);
  }
  throw new Error('Could not locate the repo root (no docker-compose.yml found above infra/)');
}

/** Same walk, for the committed shell scripts under infra/assets. */
function assetsDir(): string {
  return path.join(repoRoot(), 'infra', 'assets');
}

/** Builds the bundle and returns its path. Idempotent — safe to call per synth. */
export function buildBundle(outDir: string): string {
  const root = repoRoot();
  const dest = path.resolve(outDir, 'ragbench-bundle');

  fs.rmSync(dest, { recursive: true, force: true });
  fs.mkdirSync(dest, { recursive: true });

  for (const rel of FILES) {
    const src = path.join(root, rel);
    if (!fs.existsSync(src)) {
      throw new Error(`Bundle file missing from repo: ${rel}`);
    }
    const target = path.join(dest, rel);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.copyFileSync(src, target);
  }

  for (const rel of DIRS) {
    const src = path.join(root, rel);
    if (!fs.existsSync(src)) {
      throw new Error(`Bundle directory missing from repo: ${rel}`);
    }
    fs.cpSync(src, path.join(dest, rel), { recursive: true });
  }

  // Shipped alongside so bake and boot run the same scripts that are committed.
  fs.cpSync(assetsDir(), path.join(dest, 'scripts'), { recursive: true });

  return dest;
}
