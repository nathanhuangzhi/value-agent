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

/**
 * Swipe left/right on a ticker screen to move to the previous/next company
 * in the same industry (the carousel in app/ticker/[symbol].tsx).
 *
 * Off since 2026-09-13: the page-level pan competes with the historical
 * table's own horizontal scroll, so a swipe on the table dragged the whole
 * page too. With it off the page only scrolls vertically; navigate between
 * companies from the industry list instead.
 */
export const TICKER_SWIPE_NAV = false;
