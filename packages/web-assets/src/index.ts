export interface EmbeddedWebAsset {
  readonly contentType: string;
  readonly bodyBase64: string;
}

export type EmbeddedWebAssets = Readonly<Record<string, EmbeddedWebAsset>>;

// Development uses Vite. The service bundler replaces this module with the
// compiled Vite files so the release is one executable JavaScript artifact.
export const webAssets: EmbeddedWebAssets = {};
