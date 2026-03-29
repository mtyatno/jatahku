import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const articles = defineCollection({
  loader: glob({ pattern: '**/*.{md,mdx}', base: './src/content/articles' }),
  schema: z.object({
    title: z.string(),
    description: z.string(),
    pubDate: z.coerce.date(),
    updatedDate: z.coerce.date().optional(),
    category: z.enum(['tutorial', 'tips-keuangan', 'update-fitur']),
    author: z.string().default('Tim Jatahku'),
    cover: z.string().optional(),
    featured: z.boolean().default(false),
  }),
});

export const collections = { articles };
