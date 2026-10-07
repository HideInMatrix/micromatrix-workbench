import { X509Certificate } from 'node:crypto'

// Build-time choice only. Runtime environment variables cannot change the
// identity embedded in a distributed service.
export function buildChannel(env = process.env) {
  const value = env.MICROMATRIX_BUILD_CHANNEL || (env.GITHUB_REF_TYPE === 'tag' ? 'release' : 'development')
  if (!['release', 'development'].includes(value)) throw new Error('MICROMATRIX_BUILD_CHANNEL must be release or development')
  if (env.GITHUB_REF_TYPE === 'tag' && value !== 'release') throw new Error('Release tags cannot publish a development identity')
  return value
}

export function macSigningIdentity(env = process.env) {
  const identity = env.APPLE_SIGNING_IDENTITY || '-'
  if (buildChannel(env) === 'release') {
    const fingerprint = env.APPLE_SIGNING_CERTIFICATE_SHA1 || ''
    // Select the exact long-lived certificate, not an ambiguous display name.
    // SHA-1 is the certificate selector/requirement format required by codesign;
    // the certificate and binary signatures themselves use SHA-256.
    if (!/^[A-Fa-f0-9]{40}$/.test(fingerprint) || identity.toUpperCase() !== fingerprint.toUpperCase()) {
      throw new Error('macOS releases require APPLE_SIGNING_IDENTITY and APPLE_SIGNING_CERTIFICATE_SHA1 set to the same 40-character certificate fingerprint; no ad-hoc fallback')
    }
  }
  return identity
}

export function macReleaseRequirement(env = process.env, identifier = 'org.micromatrix.computer-use') {
  macSigningIdentity(env)
  if (buildChannel(env) !== 'release') throw new Error('Certificate requirements apply to release builds only')
  if (!/^[A-Za-z0-9.-]+$/.test(identifier)) throw new Error('Invalid signing identifier')
  return `=identifier "${identifier}" and certificate leaf = H"${env.APPLE_SIGNING_CERTIFICATE_SHA1.toUpperCase()}"`
}

export function validateMacosCertificate(pem, env = process.env, now = Date.now()) {
  macSigningIdentity(env)
  const certificate = new X509Certificate(pem)
  if (certificate.fingerprint.replaceAll(':', '').toUpperCase() !== env.APPLE_SIGNING_CERTIFICATE_SHA1?.toUpperCase()) throw new Error('Certificate does not match the pinned release fingerprint')
  // A self-signed leaf deliberately has CA:FALSE/no keyCertSign, so checkIssued
  // would reject it as an issuer. Verify its self-signature and equal names.
  if (certificate.subject !== certificate.issuer || !certificate.verify(certificate.publicKey)) throw new Error('Release certificate must be self-signed')
  if (now < Date.parse(certificate.validFrom) || now >= Date.parse(certificate.validTo)) throw new Error('Signing certificate is not currently valid')
  if (certificate.keyUsage?.length !== 1 || certificate.keyUsage[0] !== '1.3.6.1.5.5.7.3.3') throw new Error('Certificate must be restricted to code signing')
  return certificate
}
