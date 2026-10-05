const targets = {
  'darwin-arm64': 'aarch64-apple-darwin',
  'darwin-x64': 'x86_64-apple-darwin',
  'win32-x64': 'x86_64-pc-windows-msvc',
}

export function nativeBuildTarget(platform = process.platform, arch = process.arch, expected = process.env.MICROMATRIX_BUILD_TARGET) {
  const target = targets[`${platform}-${arch}`]
  if (!target) throw new Error(`Unsupported native build platform: ${platform}/${arch}`)
  if (expected && expected !== target) throw new Error(`Runner produces ${target}, not requested target ${expected}`)
  return target
}
