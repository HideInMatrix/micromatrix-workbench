import { execFileSync } from 'node:child_process'
import { randomBytes, X509Certificate } from 'node:crypto'
import { chmodSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

// Explicit one-time setup, NEVER called by the application or release workflow.
// Files only: no keychain import, trust change, TCC reset or permission request.
export function createMacosCertificate(root = process.cwd()) {
  const directory = path.join(root, '.local/macos-signing')
  if (existsSync(directory)) throw new Error('macOS signing directory already exists; refusing to replace the long-lived identity')
  mkdirSync(path.dirname(directory), { recursive: true, mode: 0o700 })
  mkdirSync(directory, { mode: 0o700 })
  const password = randomBytes(32).toString('hex')
  const run = args => {
    try {
      return execFileSync('openssl', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        timeout: 120_000, env: { ...process.env, MM_CERTIFICATE_PASSWORD: password } })
    } catch { throw new Error('Code-signing certificate creation failed; private command output withheld') }
  }
  const key = path.join(directory, 'private-key.pem')
  const certificate = path.join(directory, 'certificate.pem')
  const config = path.join(directory, 'openssl.cnf')
  writeFileSync(config, `[req]
prompt = no
distinguished_name = subject
x509_extensions = code_signing
[subject]
CN = micromatrix Long-Term Code Signing
O = micromatrix
[code_signing]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
`, { mode: 0o600, flag: 'wx' })
  try {
    run(['req', '-new', '-x509', '-newkey', 'rsa:3072', '-sha256', '-days', '3650',
      '-config', config, '-passout', 'env:MM_CERTIFICATE_PASSWORD', '-keyout', key, '-out', certificate])
    chmodSync(key, 0o600); chmodSync(certificate, 0o600)
    const p12 = path.join(directory, 'certificate.p12')
    run(['pkcs12', '-export', '-inkey', key, '-in', certificate, '-name', 'micromatrix Long-Term Code Signing',
      '-passin', 'env:MM_CERTIFICATE_PASSWORD', '-passout', 'env:MM_CERTIFICATE_PASSWORD',
      // macOS security import requires the interoperable PKCS12 envelope.
      // SHA-1 here is its HMAC/KDF, not the certificate/code signature. A random
      // 256-bit password protects the encrypted RSA key from password guessing.
      '-keypbe', 'PBE-SHA1-3DES', '-certpbe', 'PBE-SHA1-3DES', '-macalg', 'sha1', '-out', p12])
    chmodSync(p12, 0o600)
    writeFileSync(path.join(directory, 'password.txt'), password, { mode: 0o600, flag: 'wx' })
    const cert = new X509Certificate(readFileSync(certificate))
    const fingerprint = cert.fingerprint.replaceAll(':', '')
    const variables = { APPLE_SIGNING_IDENTITY: fingerprint, APPLE_SIGNING_CERTIFICATE_SHA1: fingerprint }
    writeFileSync(path.join(directory, 'variables.json'), JSON.stringify(variables, null, 2) + '\n', { mode: 0o600, flag: 'wx' })
    console.log(`Created long-lived signing certificate in ${directory}; no keychain/trust settings changed`)
    console.log(`Public certificate fingerprint: ${fingerprint}; expires ${cert.validTo}`)
    return variables
  } catch (error) {
    rmSync(directory, { recursive: true, force: true })
    throw error
  } finally {
    rmSync(key, { force: true }); rmSync(config, { force: true })
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) createMacosCertificate()
