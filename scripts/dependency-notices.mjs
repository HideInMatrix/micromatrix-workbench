import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const digest = value => createHash('sha256').update(value).digest('hex')
const json = file => JSON.parse(readFileSync(file, 'utf8'))
/** Fixed-version upstream declarations and supplemental standard texts. A
 * policy/template is labelled as such, never passed off as an upstream grant. */
export function catalogNotices(root, ecosystem, pkg, directory) {
  const catalogFile = path.join(root, 'third_party/dependencies/manifest.json')
  if (!existsSync(catalogFile)) return []
  const matches = json(catalogFile).notices.filter(entry => entry.ecosystem === ecosystem && entry.name === pkg.name && entry.version === pkg.version && entry.license === pkg.license)
  return matches.map(entry => {
    if (typeof entry.file !== 'string' || path.basename(entry.file) !== entry.file) throw Error('Invalid reviewed notice filename')
    if (ecosystem === 'cargo' && entry.vcsCommit !== json(path.join(directory, '.cargo_vcs_info.json')).git.sha1) throw Error(`Reviewed notice source changed: ${entry.name}`)
    const text = readFileSync(path.join(root, 'third_party/dependencies', entry.file), 'utf8')
    if (digest(text) !== entry.sha256) throw Error(`Reviewed notice hash changed: ${entry.name}`)
    return { file: entry.file, sha256: entry.sha256, source: entry.source, text,
      ...(entry.selectedLicense ? { selectedLicense: entry.selectedLicense, basis: entry.basis } : {}),
      ...(entry.reviewWarning ? { reviewWarning: entry.reviewWarning } : {}) }
  })
}
export function rustStandardLibraryNotice(root, sysroot, compiler) {
  const installed = path.join(sysroot, 'share/doc/rust/COPYRIGHT-library.html')
  if (existsSync(installed)) return installed
  const catalog = json(path.join(root, 'third_party/dependencies/manifest.json')).rustStandardLibrary
  if (!catalog || /^release: (.+)$/m.exec(compiler)?.[1] !== catalog.version || /^commit-hash: (.+)$/m.exec(compiler)?.[1] !== catalog.compilerCommit) return undefined
  if (typeof catalog.file !== 'string' || path.basename(catalog.file) !== catalog.file) throw Error('Invalid Rust standard-library notice filename')
  const candidate = path.join(root, 'third_party/dependencies', catalog.file)
  if (digest(readFileSync(candidate)) !== catalog.sha256) throw Error('Reviewed Rust standard-library notice changed')
  return candidate
}
function noticeFiles(directory) {
  const result = []
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name)
    if (entry.isFile() && /^(licen[cs]e|copying|copyright|notice|third.?party.?notices)([._-]|$)/i.test(entry.name)) result.push(file)
    if (entry.isDirectory() && /^(licenses|licences)$/i.test(entry.name)) {
      for (const child of readdirSync(file, { withFileTypes: true })) if (child.isFile()) result.push(path.join(file, child.name))
    }
  }
  return result.sort().map(file => {
    const content = readFileSync(file, 'utf8')
    return { file: path.relative(directory, file).replaceAll('\\', '/'), sha256: digest(content), text: content }
  })
}
function nearestPackage(file) {
  let directory = path.dirname(path.resolve(file))
  while (true) {
    const manifest = path.join(directory, 'package.json')
    if (existsSync(manifest)) {
      const pkg = json(manifest)
      if (pkg.name && pkg.version) return { directory, pkg }
    }
    const parent = path.dirname(directory)
    if (parent === directory) return undefined
    directory = parent
  }
}
function npmEntries(files, root) {
  const entries = new Map()
  for (const file of files) {
    const resolved = nearestPackage(file)
    if (!resolved || !resolved.directory.split(path.sep).includes('node_modules')) continue
    const { directory, pkg } = resolved
    const id = `${pkg.name}@${pkg.version}`
    if (entries.has(id)) continue
    let notices = noticeFiles(directory)
    // Pi packages omit LICENSE in npm tarballs. The exact locked harness
    // release is covered by the reviewed upstream license already in our repo.
    if (!notices.length && (pkg.name.startsWith('@earendil-works/pi-') || pkg.name === '@earendil-works/chord') && pkg.version === '0.87.1') {
      const text = readFileSync(path.join(root, 'third_party/pi/LICENSE'), 'utf8')
      notices = [{ file: 'upstream/Pi-LICENSE', sha256: digest(text), text }]
    }
    // This exact tarball carries its full MIT grant in README, not LICENSE.
    if (!notices.length && pkg.name === 'data-uri-to-buffer' && pkg.version === '4.0.1') {
      const text = readFileSync(path.join(directory, 'README.md'), 'utf8').split('License\n-------')[1]?.trim()
      if (text?.includes('Copyright (c) 2014 Nathan Rajlich') && text.includes('Permission is hereby granted') && text.includes('MERCHANTABILITY')) notices = [{ file: 'README.md#License', sha256: digest(text), text }]
    }
    if (!notices.length) notices = catalogNotices(root, 'npm', pkg, directory)
    const license = typeof pkg.license === 'string' ? pkg.license : pkg.license?.type ?? null
    entries.set(id, { ecosystem: 'npm', name: pkg.name, version: pkg.version, license,
      source: `https://registry.npmjs.org/${pkg.name.replace('/', '%2f')}/${pkg.version}`, notices })
  }
  return [...entries.values()].sort((a, b) => a.name.localeCompare(b.name))
}
/** Vite records modules actually used, not the npm dev/runtime flag. The
 * artifact carries notices too, so native jobs reuse the SAME frontend proof. */
export function webDependencyNotices(root) {
  return { name: 'micromatrix-web-notices', generateBundle() {
    const modules = [...this.getModuleIds()].map(id => id.split('?')[0]).filter(id => path.isAbsolute(id) && existsSync(id))
    this.emitFile({ type: 'asset', fileName: 'third-party-notices.json', source: JSON.stringify({ schema: 1, packages: npmEntries(modules, root) }, null, 2) + '\n' })
  } }
}
export function generateDependencyNotices(root = process.cwd(), { cargo = true, strict = false } = {}) {
  const require = createRequire(path.join(root, 'package.json'))
  const metadataFile = path.join(root, 'dist/service-metafile.json')
  if (!existsSync(metadataFile)) throw Error('Build the service first; notice inventory must use actual esbuild inputs')
  const metadata = json(metadataFile)
  const inputs = Object.keys(metadata.inputs).map(file => path.resolve(root, file))
  inputs.push(require.resolve('@jitl/quickjs-wasmfile-release-sync/wasm'), require.resolve('playwright-core/package.json'))
  const packages = npmEntries(inputs, root)
  const web = json(path.join(root, 'apps/web/dist/third-party-notices.json'))
  for (const entry of web.packages) if (!packages.some(pkg => pkg.ecosystem === entry.ecosystem && pkg.name === entry.name && pkg.version === entry.version)) packages.push(entry)
  if (cargo) {
    const target = process.env.MICROMATRIX_BUILD_TARGET ?? `${process.arch === 'arm64' ? 'aarch64' : 'x86_64'}-${process.platform === 'darwin' ? 'apple-darwin' : process.platform === 'win32' ? 'pc-windows-msvc' : 'unknown-linux-gnu'}`
    const data = JSON.parse(execFileSync('cargo', ['metadata', '--manifest-path', path.join(root, 'apps/desktop/Cargo.toml'), '--locked', '--offline', '--format-version', '1', '--filter-platform', target], { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 }))
    const active = new Set(data.resolve.nodes.map(node => node.id))
    for (const pkg of data.packages) if (pkg.source && active.has(pkg.id)) {
      const directory = path.dirname(pkg.manifest_path), existing = noticeFiles(directory)
      packages.push({ ecosystem: 'cargo', name: pkg.name, version: pkg.version, license: pkg.license,
        source: `https://crates.io/crates/${pkg.name}/${pkg.version}`, notices: existing.length ? existing : catalogNotices(root, 'cargo', pkg, directory) })
    }
  }
  packages.sort((a, b) => `${a.ecosystem}:${a.name}@${a.version}`.localeCompare(`${b.ecosystem}:${b.name}@${b.version}`))
  const missing = packages.filter(pkg => !pkg.license || !pkg.notices.length).map(({ ecosystem, name, version, license }) => ({ ecosystem, name, version, license }))
  const output = path.join(root, 'dist/dependency-notices'); rmSync(output, { recursive: true, force: true }); mkdirSync(output, { recursive: true })
  const rustRoot = cargo ? execFileSync('rustc', ['--print', 'sysroot'], { encoding: 'utf8' }).trim() : undefined
  // Minimal CI rustup profiles omit rust-docs. Use the reviewed component text
  // only for the exact compiler release+commit, not "latest" or another SDK.
  const rustNotice = rustRoot ? rustStandardLibraryNotice(root, rustRoot, execFileSync('rustc', ['-vV'], { encoding: 'utf8' })) : undefined
  if (rustNotice && existsSync(rustNotice)) writeFileSync(path.join(output, 'RUST_LIBRARY_COPYRIGHT.html'), readFileSync(rustNotice))
  const manifest = { schema: 1, reviewWarnings: [...new Set(['Prebuilt cloudflared transitive modules and QuickJS WASM toolchain runtime still require separate notice review; package metadata and files alone do not establish full legal compliance.', ...packages.flatMap(pkg => pkg.notices.flatMap(notice => notice.reviewWarning ? [notice.reviewWarning] : []))])], rustStandardLibraryNotice: Boolean(rustNotice && existsSync(rustNotice)), scope: 'Actual esbuild/Vite npm modules and copied Playwright/WASM; Cargo target resolve graph is a conservative superset including build dependencies. Node, cloudflared, ASIL and reviewed automation notices are separately bundled. Native SDK obligations and opaque prebuilt dependencies are outside this graph.',
    inventoryNoticeFilesComplete: cargo && missing.length === 0 && Boolean(rustNotice && existsSync(rustNotice)), legalReviewComplete: false, cargoIncluded: cargo, missingNotices: missing, packages }
  // No build-machine paths or private registry credentials in shipped metadata.
  writeFileSync(path.join(output, 'DEPENDENCIES.json'), JSON.stringify(manifest, null, 2) + '\n')
  const sourceAvailable = packages.filter(pkg => /MPL-2.0/.test(pkg.license ?? ''))
  writeFileSync(path.join(output, 'SOURCE_AVAILABILITY.txt'), 'Unmodified MPL-2.0 dependencies: the exact upstream source archives are available below. Their original notices are included in DEPENDENCY_LICENSES.txt when present. Missing notices still require review; this inventory is not a legal-compliance guarantee.\n\n' + sourceAvailable.map(pkg => `${pkg.name}@${pkg.version}: https://static.crates.io/crates/${pkg.name}/${pkg.name}-${pkg.version}.crate\n`).join(''))
  writeFileSync(path.join(output, 'DEPENDENCY_LICENSES.txt'), packages.map(pkg => `\n${'='.repeat(72)}\n${pkg.ecosystem}:${pkg.name}@${pkg.version} — ${pkg.license ?? 'UNDECLARED'}\nSource: ${pkg.source}\n${pkg.notices.map(notice => `\n${notice.file} [SHA256 ${notice.sha256}]\n${notice.text}`).join('\n') || 'NOTICE MISSING: requires upstream review before claiming complete compliance.'}\n`).join(''))
  console.log(`Dependency inventory: ${packages.length} packages, ${missing.length} missing notice/license records; Cargo ${cargo ? 'included' : 'not yet included'}`)
  if (strict && !manifest.inventoryNoticeFilesComplete) throw Error('Dependency notices are incomplete; inspect dist/dependency-notices/DEPENDENCIES.json')
  return output
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) generateDependencyNotices(process.cwd(), { cargo: !process.argv.includes('--npm-only'), strict: process.argv.includes('--strict') })
