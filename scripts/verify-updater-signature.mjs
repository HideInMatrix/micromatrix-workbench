import { createHash, createPublicKey, verify } from 'node:crypto'

// Tauri's .sig is base64-encoded minisign text. Verify both the artifact and
// trusted comment, including key ID, before publishing any updater manifest.
export function verifyUpdaterSignature(bytes, signature, publicKey, expectedVersion) {
  const keyLines = Buffer.from(publicKey.trim(), 'base64').toString('utf8').trim().split(/\r?\n/)
  const lines = Buffer.from(signature.trim(), 'base64').toString('utf8').trim().split(/\r?\n/)
  const key = Buffer.from(keyLines[1] ?? '', 'base64')
  const sig = Buffer.from(lines[1] ?? '', 'base64')
  const global = Buffer.from(lines[3] ?? '', 'base64')
  if (key.length !== 42 || sig.length !== 74 || global.length !== 64 || !lines[2]?.startsWith('trusted comment: ')) throw new Error('Invalid updater signature encoding')
  if (!key.subarray(2, 10).equals(sig.subarray(2, 10))) throw new Error('Updater signature key ID mismatch')
  const algorithm = sig.subarray(0, 2).toString()
  if (!['Ed', 'ED'].includes(algorithm)) throw new Error('Unsupported updater signature algorithm')
  const edKey = createPublicKey({ key: Buffer.concat([Buffer.from('302a300506032b6570032100', 'hex'), key.subarray(10)]), format: 'der', type: 'spki' })
  const message = algorithm === 'ED' ? createHash('blake2b512').update(bytes).digest() : bytes
  const artifactSignature = sig.subarray(10)
  const trustedComment = lines[2].slice('trusted comment: '.length)
  const comment = Buffer.from(trustedComment)
  if (expectedVersion && trustedComment.split('\t').find(field => field.startsWith('version:'))?.slice(8) !== expectedVersion) throw new Error('Updater signed version mismatch')
  if (!verify(null, message, edKey, artifactSignature) || !verify(null, Buffer.concat([artifactSignature, comment]), edKey, global)) throw new Error('Updater signature verification failed')
}
