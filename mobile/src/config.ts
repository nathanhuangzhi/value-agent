/**
 * App-wide feature flags. Flip + `eas update` to roll out.
 */

/**
 * Show the DeepSeek-written analysis: the per-ticker "Investment Narrative",
 * the "Stories of the day" digest / industry summaries, and the summary
 * teaser on home-screen batch cards.
 *
 * Off since 2026-09-13: the daily pipeline runs with the LLM stages
 * disabled (see deploy/run_daily.sh LLM_DEFAULT), so the narratives on
 * disk are stale (last written 2026-07-22). Set true to show them again.
 */
export const SHOW_LLM_ANALYSIS = false;
