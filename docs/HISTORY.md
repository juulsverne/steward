# Commit identity cleanup

On September 14, 2026, the owner requested consistent attribution to Elijah Leung and removal of automated Claude co-author footers. Author and committer identities were normalized; technical commit descriptions, dates, merge relationships and every source tree were preserved.

The [commit mapping](commit-history-map.tsv) translates original full commit IDs to updated IDs. Dated evaluation and deployment receipts retain the IDs recorded when those checks ran; use this mapping to find the same source snapshot in the updated history. This metadata change did not redeploy the application or rerun its evaluations. Documentation of AI tools and asset provenance remains intact.

Existing clones and development worktrees still based on the original history should preserve local work, then fetch and move to the updated branch (a fresh clone is simplest). Do not merge the old history back into the published branches. A complete pre-cleanup Git bundle is retained locally under the ignored `.steward/history-cleanup/` directory.
