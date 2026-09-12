import { defineConfig, presetWind4 } from 'unocss'
import { presetShadcn } from 'unocss-preset-shadcn'

export default defineConfig({
  presets: [
    presetWind4({
      preflights: {
        reset: true,
        theme: true,
      },
    }),
    presetShadcn(
      {
        color: 'blue',
      },
      {
        componentLibrary: 'reka',
      },
    ),
  ],
  content: {
    pipeline: {
      include: [
        /\.(vue|svelte|[jt]sx|mdx?|astro|elm|php|phtml|html)($|\?)/,
        '(components|src)/**/*.{js,ts}',
      ],
    },
  },
  theme: {
    colors: {
      success: 'var(--success)',
      warning: 'var(--warning)',
    },
  },
})
